"""Agent pipeline tests with a mocked Anthropic client (no network, no API key)."""

import copy
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from epi_risk_agent.agent import (
    FALLBACK_BETA,
    WEB_FETCH_TOOL,
    WEB_SEARCH_TOOL,
    AgentConfig,
    AgentError,
    RiskAgent,
    SourceRegistry,
    classify,
    extract_json,
    to_strict_schema,
)
from epi_risk_agent.ingest import ingest_text
from epi_risk_agent.schema import llm_output_schema

NOW = datetime.fromisoformat("2026-11-19T11:40:00+08:00")


def msg(content, stop="end_turn"):
    return SimpleNamespace(content=content, stop_reason=stop, model="claude-opus-5-5", stop_details=None,
                           usage=SimpleNamespace(input_tokens=10, output_tokens=20, cache_read_input_tokens=0))


def text(t, citations=None):
    return {"type": "text", "text": t, "citations": citations}


class FakeStream:
    def __init__(self, m):
        self.m = m

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.m


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return FakeStream(r)


CLAIMS = {
    "news_title": "WHO Reports First MERS Cases in Qatar Since 2022", "news_publisher": "Archyde", "news_date": None,
    "hazard": "MERS-CoV", "event_location": "卡達", "event_type": ["人畜共通"], "taiwan_relevance": "第五類法定傳染病",
    "triage_decision": "進行完整評估", "triage_reason": "高致死率", "news_summary": "卡達 2 例",
    "claims": [{"text": "WHO 公布卡達 2 例", "importance": "關鍵"}],
}


def search_result(urls):
    return {"type": "web_search_tool_result", "tool_use_id": "t1",
            "content": [{"type": "web_search_result", "url": u, "title": f"title {k}", "page_age": "November 13, 2026"}
                        for k, u in enumerate(urls)]}


def fetch_result(url):
    return {"type": "web_fetch_tool_result", "tool_use_id": "t2",
            "content": {"type": "web_fetch_result", "url": url, "content": {"type": "document", "title": "Fetched"}}}


@pytest.fixture
def scripted(data):
    """Responses for a full successful run that reproduces the worked example."""
    urls = [s["url"] for s in data["sources"][1:]]  # S2..S13 in order
    final = copy.deepcopy(data)
    final.pop("audit", None)
    for s in final["sources"]:
        s["url"] = "https://evil.example/fabricated"  # must be overwritten from the registry
    final["sources"].append({"id": "S77", "url": "https://made.up/x", "title": "x", "publisher": "x", "tier": 1,
                             "retrieval": "全文"})  # not in registry -> dropped
    responses = [
        msg([text(json.dumps(CLAIMS, ensure_ascii=False))]),
        # verify: a paused turn first, then the search + fetch results
        msg([{"type": "server_tool_use", "id": "t1", "name": "web_search", "input": {"query": "MERS Qatar"}},
             search_result(urls[:6])], stop="pause_turn"),
        msg([fetch_result(urls[0]), text("查證筆記：C1 已證實", citations=[{"type": "web_search_result_location", "url": urls[0], "cited_text": "two laboratory-confirmed cases"}])]),
        msg([search_result(urls[6:]), text("證據筆記")]),
        msg([text("```json\n" + json.dumps(final, ensure_ascii=False) + "\n```")]),
    ]
    return responses


def make_agent(responses, **cfg):
    client = FakeClient(responses)
    progress = []
    agent = RiskAgent(client=client, config=AgentConfig(model="claude-opus-5-5", **cfg),
                      progress=lambda s, m: progress.append((s, m)))
    return agent, client, progress


def news():
    n = ingest_text("卡達出現 2 例 MERS", origin="https://www.archyde.com/who-reports-first-mers-cases-in-qatar-since-2022/")
    n.title = "WHO Reports First MERS Cases in Qatar Since 2022"
    return n


def test_full_pipeline(scripted, data):
    agent, client, progress = make_agent(scripted)
    res = agent.run(news(), now=NOW)
    a = res.assessment
    # deterministic result reproduced
    assert a.audit.overall_computed_level == "低"
    assert a.audit.overall_agrees
    # every URL comes from the registry (what the API returned), none fabricated
    urls = {s.url for s in a.sources}
    assert "https://evil.example/fabricated" not in urls and "https://made.up/x" not in urls
    assert [s.url for s in a.sources] == [s["url"] for s in data["sources"]]
    s2 = next(s for s in a.sources if s.id == "S2")
    assert s2.retrieval == "全文"  # upgraded because it was fetched
    s3 = next(s for s in a.sources if s.id == "S3")
    assert s3.retrieval == "搜尋摘要" and s3.accessed_date == "2026-11-19"
    assert a.sources[0].is_news_item
    # 5 API calls: claims, verify (pause + resume), context, assess
    assert len(client.calls) == 5
    assert [p[0] for p in progress][0] == "claims" and progress[-1][0] == "done"


def test_request_shape(scripted):
    agent, client, _ = make_agent(scripted)
    agent.run(news(), now=NOW)
    first, verify = client.calls[0], client.calls[1]
    for c in client.calls:
        assert c["model"] == "claude-opus-5-5"
        assert c["thinking"] == {"type": "adaptive"}
        assert c["output_config"]["effort"] == "high"
        assert c["fallbacks"] == "default" and FALLBACK_BETA in c["betas"]
        assert c["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert "疫情快速風險評估方法" in c["system"][0]["text"]
        assert "temperature" not in c and "budget_tokens" not in json.dumps(c["thinking"])
    assert "tools" not in first and first["output_config"]["format"]["type"] == "json_schema"
    assert [t["type"] for t in verify["tools"]] == [WEB_SEARCH_TOOL, WEB_FETCH_TOOL]
    # pause_turn resume re-sends the assistant content without an extra user turn
    resume = client.calls[2]
    assert resume["messages"][-1]["role"] == "assistant"
    assert len(resume["messages"]) == len(verify["messages"]) + 1


def test_repair_retry_on_invalid_json(scripted):
    good = scripted[-1]
    scripted[-1] = msg([text('{"report_title": "缺很多欄位"}')])
    scripted.append(good)
    agent, client, progress = make_agent(scripted)
    res = agent.run(news(), now=NOW)
    assert res.assessment.audit.overall_computed_level == "低"
    repair_msgs = client.calls[-1]["messages"]
    assert repair_msgs[-1]["role"] == "user" and "未通過驗證" in repair_msgs[-1]["content"]
    assert any("未通過驗證" in m for _, m in progress)


def test_repair_exhausted_raises(scripted):
    scripted[-1] = msg([text("not json")])
    scripted += [msg([text("still not json")]), msg([text("nope")])]
    agent, _, _ = make_agent(scripted)
    with pytest.raises(AgentError, match="修正"):
        agent.run(news(), now=NOW)


def test_unknown_citation_triggers_repair(scripted, data):
    bad = json.loads(scripted[-1].content[0]["text"].strip("`json\n"))
    bad["risk_items"][0]["evidence"][0]["source_ids"] = ["S77"]
    good = scripted[-1]
    scripted[-1] = msg([text(json.dumps(bad, ensure_ascii=False))])
    scripted.append(good)
    agent, client, _ = make_agent(scripted)
    agent.run(news(), now=NOW)
    assert "來源登錄表以外" in client.calls[-1]["messages"][-1]["content"]


def test_refusal_raises():
    agent, _, _ = make_agent([SimpleNamespace(content=[], stop_reason="refusal", model="m",
                                              stop_details=SimpleNamespace(category="bio"), usage=None)])
    with pytest.raises(AgentError, match="拒絕"):
        agent.run(news(), now=NOW)


def test_structured_output_rejected_falls_back(scripted):
    import anthropic
    import httpx

    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.BadRequestError("schema too complex", response=httpx.Response(400, request=req), body=None)
    scripted.insert(0, err)
    agent, client, progress = make_agent(scripted)
    agent.run(news(), now=NOW)
    assert "format" not in client.calls[1]["output_config"]
    assert "JSON Schema" in client.calls[1]["messages"][-1]["content"]


def test_options_disable_fallbacks_and_domains(scripted):
    agent, client, _ = make_agent(scripted, use_fallbacks=False, allowed_domains=["who.int"])
    agent.run(news(), now=NOW)
    assert "fallbacks" not in client.calls[0] and "betas" not in client.calls[0]
    assert client.calls[1]["tools"][0]["allowed_domains"] == ["who.int"]


def test_registry_harvest_and_error_results():
    reg = SourceRegistry("2026-11-19")
    reg.harvest([
        {"type": "web_search_tool_result", "content": {"type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"}},
        search_result(["https://www.who.int/a", "https://www.cdc.gov.tw/b/"]),
        fetch_result("https://www.cdc.gov.tw/b"),
    ])
    s = reg.sources()
    assert [x["id"] for x in s] == ["S1", "S2"]
    assert s[1]["retrieval"] == "全文" and s[1]["publisher"] == "衛生福利部疾病管制署" and s[1]["tier"] == 1
    assert s[0]["published_date"] == "2026-11-13"


def test_classify_and_helpers():
    assert classify("https://www.ecdc.europa.eu/x")[1] == 1
    assert classify("https://pubmed.ncbi.nlm.nih.gov/1/")[1] == 2
    assert classify("https://www.reuters.com/x")[1] == 3
    assert classify("https://random.blog/x")[1] == 4
    assert extract_json("前言\n```json\n{\"a\": 1}\n```") == {"a": 1}
    strict = to_strict_schema(llm_output_schema())
    dumped = json.dumps(strict)
    assert '"minimum"' not in dumped and '"maximum"' not in dumped
    assert strict["additionalProperties"] is False
    assert all(d.get("additionalProperties") is False for d in strict["$defs"].values() if d.get("type") == "object")
