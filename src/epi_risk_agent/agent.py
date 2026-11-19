"""Claude API pipeline (official ``anthropic`` SDK).

Stages
------
1. 分流與陳述擷取     – structured output, no tools
2. 多來源查證         – server-side web_search / web_fetch, free-text notes
3. 我國情境證據蒐集   – server-side web_search / web_fetch, free-text notes
4. 結構化評估 JSON    – structured output against the Assessment schema,
                         pydantic validation + repair retry
5. 確定性計分與檢核   – scoring.apply_audit (no LLM)

Provenance design: the source registry is built *by code* from the
``web_search_tool_result`` / ``web_fetch_tool_result`` / citation blocks that
the API actually returned. Stage 4 may only cite registry ids, and every URL in
the final JSON is overwritten from the registry, so the model cannot introduce
a URL that was not retrieved in this run.
"""

from __future__ import annotations

import copy
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from importlib import resources
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, ValidationError

from .ingest import IngestedNews
from .schema import Assessment, llm_output_schema
from .scoring import apply_audit

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
WEB_SEARCH_TOOL = "web_search_20260209"
WEB_FETCH_TOOL = "web_fetch_20260209"
TAIPEI = timezone(timedelta(hours=8))

ProgressFn = Callable[[str, str], None]


class AgentError(RuntimeError):
    pass


@dataclass
class AgentConfig:
    model: str = field(default_factory=lambda: os.environ.get("EPI_RISK_MODEL", DEFAULT_MODEL))
    effort: str = field(default_factory=lambda: os.environ.get("EPI_RISK_EFFORT", "high"))
    max_tokens: int = 64000
    web_search_max_uses: int = 12
    web_fetch_max_uses: int = 10
    use_fallbacks: bool = True
    structured_output: bool = True
    max_repairs: int = 2
    max_continuations: int = 6
    allowed_domains: Optional[list[str]] = None
    reassess_days: int = 28


# ---------------------------------------------------------------------------
# prompts
# ---------------------------------------------------------------------------


def load_prompt(name: str) -> str:
    return resources.files("epi_risk_agent").joinpath("prompts", name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# JSON schema helpers for structured outputs
# ---------------------------------------------------------------------------

_DROP_KEYS = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength",
              "minItems", "maxItems", "pattern", "default", "multipleOf", "uniqueItems"}
_ALLOWED_FORMATS = {"date-time", "time", "date", "duration", "email", "hostname", "uri", "ipv4", "ipv6", "uuid"}


def to_strict_schema(schema: dict) -> dict:
    """Make a pydantic JSON schema acceptable to structured outputs:
    ``additionalProperties: false`` on every object, unsupported constraints
    removed (pydantic re-validates them client-side afterwards)."""

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k in _DROP_KEYS:
                    continue
                if k == "format" and v not in _ALLOWED_FORMATS:
                    continue
                out[k] = walk(v)
            if out.get("type") == "object" or "properties" in out:
                out["additionalProperties"] = False
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(copy.deepcopy(schema))


class ExtractedClaim(BaseModel):
    text: str
    importance: str = Field(description="關鍵 或 次要")


class ClaimsExtraction(BaseModel):
    news_title: str
    news_publisher: Optional[str] = None
    news_date: Optional[str] = None
    hazard: str
    event_location: str
    event_type: list[str]
    taiwan_relevance: str
    triage_decision: str = Field(description="進行完整評估／持續監測／不需處理")
    triage_reason: str
    news_summary: str
    claims: list[ExtractedClaim]


# ---------------------------------------------------------------------------
# Source registry built from what the API actually retrieved
# ---------------------------------------------------------------------------

PUBLISHERS = {
    "who.int": ("World Health Organization", 1),
    "cdc.gov.tw": ("衛生福利部疾病管制署", 1),
    "mohw.gov.tw": ("衛生福利部", 1),
    "ecdc.europa.eu": ("European Centre for Disease Prevention and Control", 1),
    "cdc.gov": ("US Centers for Disease Control and Prevention", 1),
    "paho.org": ("Pan American Health Organization", 1),
    "niid.go.jp": ("National Institute of Infectious Diseases (Japan)", 1),
    "jihs.go.jp": ("Japan Institute for Health Security", 1),
    "kdca.go.kr": ("Korea Disease Control and Prevention Agency", 1),
    "chp.gov.hk": ("香港衛生防護中心", 1),
    "gov.uk": ("UK Government (UKHSA)", 1),
    "promedmail.org": ("ProMED", 3),
    "pubmed.ncbi.nlm.nih.gov": ("PubMed", 2),
    "ncbi.nlm.nih.gov": ("PubMed Central", 2),
    "doi.org": ("DOI", 2),
    "nejm.org": ("New England Journal of Medicine", 2),
    "thelancet.com": ("The Lancet", 2),
    "cambridge.org": ("Cambridge University Press", 2),
    "eurosurveillance.org": ("Eurosurveillance", 2),
    "reuters.com": ("Reuters", 3),
    "apnews.com": ("Associated Press", 3),
    "bbc.com": ("BBC", 3),
    "cna.com.tw": ("中央通訊社", 3),
    "focustaiwan.tw": ("Focus Taiwan (CNA)", 3),
    "cidrap.umn.edu": ("CIDRAP", 3),
}


def domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def classify(url: str) -> tuple[str, int]:
    host = domain_of(url)
    for dom, (pub, tier) in PUBLISHERS.items():
        if host == dom or host.endswith("." + dom):
            return pub, tier
    if host.endswith(".gov") or host.endswith(".gov.tw") or ".gov." in host or host.endswith(".int"):
        return host, 1
    if host.endswith(".edu") or host.endswith(".ac.uk"):
        return host, 2
    return host or "未知", 4


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _norm_url(u: str) -> str:
    return u.split("#")[0].rstrip("/")


class SourceRegistry:
    def __init__(self, accessed: str):
        self.accessed = accessed
        self._by_url: dict[str, dict] = {}
        self._order: list[str] = []
        self.quotes: dict[str, list[str]] = {}

    def add(self, url: Optional[str], title: Optional[str], retrieval: str, *, published: Optional[str] = None,
            is_news: bool = False, publisher: Optional[str] = None, tier: Optional[int] = None) -> str:
        key = _norm_url(url) if url else f"__news__{len(self._order)}"
        if key in self._by_url:
            s = self._by_url[key]
            if retrieval == "全文":
                s["retrieval"] = "全文"
            if title and (not s["title"] or s["title"] == s["url"]):
                s["title"] = title
            if published and not s["published_date"]:
                s["published_date"] = published
            return s["id"]
        pub, t = classify(url) if url else ("使用者提供", 4)
        sid = f"S{len(self._order) + 1}"
        self._by_url[key] = {
            "id": sid, "url": url, "title": (title or url or "使用者提供之新聞").strip()[:300],
            "publisher": publisher or pub, "published_date": published, "accessed_date": self.accessed,
            "tier": tier or t, "retrieval": retrieval, "is_news_item": is_news, "note": None,
        }
        self._order.append(key)
        return sid

    def add_quote(self, url: str, text: str) -> None:
        sid = self.add(url, None, "搜尋摘要")
        lst = self.quotes.setdefault(sid, [])
        if text and text not in lst and len(lst) < 5:
            lst.append(text.strip()[:240])

    def harvest(self, content: list[Any]) -> None:
        """Record every source the API actually returned in a message."""
        for block in content or []:
            btype = _get(block, "type")
            if btype == "web_search_tool_result":
                results = _get(block, "content")
                if isinstance(results, list):  # list = success; object = error
                    for r in results:
                        if _get(r, "type") == "web_search_result" and _get(r, "url"):
                            self.add(_get(r, "url"), _get(r, "title"), "搜尋摘要", published=_page_age(_get(r, "page_age")))
            elif btype == "web_fetch_tool_result":
                res = _get(block, "content")
                if _get(res, "type") == "web_fetch_result" and _get(res, "url"):
                    doc = _get(res, "content")
                    self.add(_get(res, "url"), _get(doc, "title"), "全文")
            elif btype == "text":
                for c in _get(block, "citations") or []:
                    if _get(c, "url"):
                        self.add_quote(_get(c, "url"), _get(c, "cited_text") or "")

    def sources(self) -> list[dict]:
        return [self._by_url[k] for k in self._order]

    def table(self) -> str:
        lines = ["| 代碼 | 發布者 | 等級 | 取得方式 | 標題 | 網址 |", "|---|---|---|---|---|---|"]
        for s in self.sources():
            lines.append(f"| {s['id']} | {s['publisher']} | {s['tier']} | {s['retrieval']} | {s['title']} | {s['url'] or '—'} |")
        for sid, qs in self.quotes.items():
            lines.append(f"\n{sid} 引文：" + "／".join(qs))
        return "\n".join(lines)


def _page_age(v: Any) -> Optional[str]:
    if not v or not isinstance(v, str):
        return None
    m = re.search(r"(\d{4}-\d{2}-\d{2})", v)
    if m:
        return m.group(1)
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y"):
        try:
            return datetime.strptime(v.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def extract_json(text: str) -> Any:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    if not text.startswith("{"):
        i, j = text.find("{"), text.rfind("}")
        if i >= 0 and j > i:
            text = text[i:j + 1]
    return json.loads(text)


def _text_of(content: list[Any]) -> str:
    return "\n".join(_get(b, "text") or "" for b in content if _get(b, "type") == "text").strip()


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    assessment: Assessment
    registry: SourceRegistry
    log: list[dict]


class RiskAgent:
    def __init__(self, client: Any = None, config: Optional[AgentConfig] = None, progress: Optional[ProgressFn] = None):
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client
        self.cfg = config or AgentConfig()
        self.progress = progress or (lambda stage, msg: None)
        self.log: list[dict] = []
        self.system = [{"type": "text", "text": load_prompt("methodology.md"), "cache_control": {"type": "ephemeral"}}]

    # -- low level ---------------------------------------------------------
    def _tools(self) -> list[dict]:
        search: dict[str, Any] = {"type": WEB_SEARCH_TOOL, "name": "web_search", "max_uses": self.cfg.web_search_max_uses}
        fetch: dict[str, Any] = {"type": WEB_FETCH_TOOL, "name": "web_fetch", "max_uses": self.cfg.web_fetch_max_uses}
        if self.cfg.allowed_domains:
            search["allowed_domains"] = list(self.cfg.allowed_domains)
            fetch["allowed_domains"] = list(self.cfg.allowed_domains)
        return [search, fetch]

    def _call(self, stage: str, messages: list[dict], *, tools: Optional[list[dict]] = None,
              schema: Optional[dict] = None, registry: Optional[SourceRegistry] = None) -> tuple[Any, list[Any]]:
        """One logical turn; resumes ``pause_turn`` and returns (final message, all content blocks)."""
        msgs = list(messages)
        all_blocks: list[Any] = []
        for attempt in range(self.cfg.max_continuations + 1):
            kwargs: dict[str, Any] = {
                "model": self.cfg.model,
                "max_tokens": self.cfg.max_tokens,
                "system": self.system,
                "messages": msgs,
                "thinking": {"type": "adaptive"},
                "output_config": {"effort": self.cfg.effort},
            }
            betas: list[str] = []
            if tools:
                kwargs["tools"] = tools
            if schema is not None:
                kwargs["output_config"]["format"] = {"type": "json_schema", "schema": schema}
            if self.cfg.use_fallbacks:
                betas.append(FALLBACK_BETA)
                kwargs["fallbacks"] = "default"
            if betas:
                kwargs["betas"] = betas
            with self.client.beta.messages.stream(**kwargs) as stream:
                msg = stream.get_final_message()
            content = list(_get(msg, "content") or [])
            all_blocks.extend(content)
            if registry is not None:
                registry.harvest(content)
            usage = _get(msg, "usage")
            self.log.append({"stage": stage, "attempt": attempt, "stop_reason": _get(msg, "stop_reason"),
                             "model": _get(msg, "model"),
                             "input_tokens": _get(usage, "input_tokens"), "output_tokens": _get(usage, "output_tokens"),
                             "cache_read_input_tokens": _get(usage, "cache_read_input_tokens")})
            stop = _get(msg, "stop_reason")
            if stop == "refusal":
                details = _get(msg, "stop_details")
                raise AgentError(f"{stage}: 模型拒絕回應（category={_get(details, 'category')}）")
            if stop == "pause_turn":
                msgs = msgs + [{"role": "assistant", "content": content}]
                continue
            if stop == "max_tokens":
                raise AgentError(f"{stage}: 輸出達 max_tokens 上限，結果可能不完整")
            return msg, all_blocks
        raise AgentError(f"{stage}: 伺服器端工具連續暫停超過 {self.cfg.max_continuations} 次")

    def _structured(self, stage: str, messages: list[dict], schema: dict, registry: Optional[SourceRegistry] = None):
        """Structured-output call with a graceful fallback to prompt-only JSON."""
        if self.cfg.structured_output:
            try:
                msg, _ = self._call(stage, messages, schema=to_strict_schema(schema), registry=registry)
                return msg
            except AgentError:
                raise
            except Exception as e:  # noqa: BLE001 - e.g. schema rejected (400); retry without format
                import anthropic

                if not isinstance(e, anthropic.BadRequestError):
                    raise
                self.progress(stage, f"結構化輸出不被接受，改以提示詞要求 JSON：{e}")
        hint = {"role": "user", "content": "請只輸出一個 JSON 物件（可置於 ```json 區塊），符合下列 JSON Schema：\n" + json.dumps(schema, ensure_ascii=False)}
        msg, _ = self._call(stage, messages + [hint], registry=registry)
        return msg

    # -- stages -------------------------------------------------------------
    def extract_claims(self, news: IngestedNews) -> ClaimsExtraction:
        self.progress("claims", "分流並擷取可查證陳述")
        messages = [{"role": "user", "content": news.as_content_blocks() + [{"type": "text", "text": load_prompt("stage1_claims.md")}]}]
        msg = self._structured("claims", messages, ClaimsExtraction.model_json_schema())
        return ClaimsExtraction.model_validate(extract_json(_text_of(_get(msg, "content") or [])))

    def research(self, stage: str, prompt_file: str, payload: str, registry: SourceRegistry) -> str:
        messages = [{"role": "user", "content": load_prompt(prompt_file) + "\n\n" + payload}]
        msg, blocks = self._call(stage, messages, tools=self._tools(), registry=registry)
        return _text_of(blocks)

    def assess(self, news: IngestedNews, ex: ClaimsExtraction, verify_notes: str, context_notes: str,
               registry: SourceRegistry, now: datetime) -> Assessment:
        self.progress("assess", "產出結構化評估 JSON")
        schema = llm_output_schema()
        brief = (
            f"{load_prompt('stage4_assess.md')}\n\n"
            f"產出時間（generated_at）：{now.isoformat(timespec='seconds')}\n"
            f"資料截止（data_cutoff）：{now.isoformat(timespec='seconds')}\n"
            f"建議再評估日期預設：{(now + timedelta(days=self.cfg.reassess_days)).date().isoformat()}\n"
            f"模型：{self.cfg.model}\n\n"
            f"## 新聞（S1）\n{news.text[:20000]}\n\n"
            f"## 階段一結果\n{ex.model_dump_json(indent=1)}\n\n"
            f"## 查證筆記\n{verify_notes}\n\n## 證據筆記\n{context_notes}\n\n"
            f"## 來源登錄表（只能引用這些代碼）\n{registry.table()}\n"
        )
        messages: list[dict] = [{"role": "user", "content": brief}]
        last_err = ""
        for attempt in range(self.cfg.max_repairs + 1):
            msg = self._structured("assess" if attempt == 0 else f"repair{attempt}", messages, schema)
            raw = _text_of(_get(msg, "content") or [])
            try:
                data = extract_json(raw)
                data = self._merge_registry(data, registry)
                a = Assessment.model_validate(data)
                audited = apply_audit(a)
                unknown = [i for i in audited.audit.issues if i.code == "unknown_source"]
                if unknown and attempt < self.cfg.max_repairs:
                    raise ValueError("引用了來源登錄表以外之代碼：" + "；".join(f"{i.path}:{i.message}" for i in unknown[:20]))
                return audited
            except (ValueError, ValidationError, json.JSONDecodeError) as e:
                last_err = str(e)[:6000]
                self.progress("assess", f"第 {attempt + 1} 次輸出未通過驗證，要求修正")
                messages = messages + [
                    {"role": "assistant", "content": raw or "（空白）"},
                    {"role": "user", "content": f"上一個 JSON 未通過驗證，請修正後輸出完整 JSON（不要省略任何欄位）。錯誤：\n{last_err}"},
                ]
        raise AgentError(f"評估 JSON 經 {self.cfg.max_repairs} 次修正仍未通過驗證：{last_err}")

    @staticmethod
    def _merge_registry(data: dict, registry: SourceRegistry) -> dict:
        """Replace the model's ``sources`` with the code-built registry.

        The model may refine title / publisher / published_date / tier / note for
        an id that exists in the registry, but URL, retrieval mode and accessed
        date always come from the registry. Ids not in the registry are dropped
        (citations to them are then reported by scoring as ``unknown_source``).
        """
        reg = {s["id"]: dict(s) for s in registry.sources()}
        for s in data.get("sources") or []:
            sid = s.get("id") if isinstance(s, dict) else None
            if sid in reg:
                for k in ("title", "publisher", "published_date", "note"):
                    if s.get(k):
                        reg[sid][k] = s[k]
                if s.get("tier") in (1, 2, 3, 4) and reg[sid]["tier"] == 4:
                    reg[sid]["tier"] = s["tier"]
        data["sources"] = list(reg.values())
        data["audit"] = None
        return data

    # -- orchestration --------------------------------------------------------
    def run(self, news: IngestedNews, now: Optional[datetime] = None) -> RunResult:
        now = now or datetime.now(TAIPEI)
        registry = SourceRegistry(accessed=now.date().isoformat())
        news_url = news.origin if re.match(r"^https?://", news.origin) else None
        registry.add(news_url, news.title or "使用者提供之新聞", "全文", is_news=True)

        ex = self.extract_claims(news)
        claims_list = "\n".join(f"C{i}. {c.text}（{c.importance}）" for i, c in enumerate(ex.claims, start=1))
        self.progress("verify", f"以網路搜尋查證 {len(ex.claims)} 則陳述")
        verify_notes = self.research("verify", "stage2_verify.md",
                                     f"事件：{ex.hazard}／{ex.event_location}\n新聞：{ex.news_title}（{ex.news_publisher or '發布者不明'}）\n\n待查證陳述：\n{claims_list}",
                                     registry)
        self.progress("context", "蒐集病原特性、國際疫情與我國現況證據")
        context_notes = self.research("context", "stage3_context.md",
                                      f"事件：{ex.hazard}／{ex.event_location}\n與臺灣相關性：{ex.taiwan_relevance}\n\n已知查證筆記摘要：\n{verify_notes[:6000]}",
                                      registry)
        a = self.assess(news, ex, verify_notes, context_notes, registry, now)
        self.progress("done", f"完成：整體風險（計算）{a.audit.overall_computed_level}")
        return RunResult(assessment=a, registry=registry, log=self.log)
