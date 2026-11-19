import json
import re

from epi_risk_agent.render import render_html
from epi_risk_agent.schema import Assessment
from epi_risk_agent.scoring import RISK_MATRIX

SECTIONS = ["sec-bluf", "sec-decision", "sec-verify", "sec-situation", "sec-risk", "sec-scenario", "sec-recs", "sec-limits"]
HEADINGS = ["決策摘要", "長官下一步決策建議", "新聞查證", "疫情概況", "風險評估表", "情境分析", "建議事項", "限制與不確定性"]


def _html(data):
    return render_html(Assessment.model_validate(data))


def test_all_sections_present_in_order(data):
    html = _html(data)
    pos = [html.index(f'id="{s}"') for s in SECTIONS]
    assert pos == sorted(pos)
    for h in HEADINGS:
        assert h in html


def test_no_external_resources(data):
    html = _html(data)
    for tag, attr in (("script", "src"), ("link", "href"), ("img", "src"), ("iframe", "src"), ("source", "src")):
        for m in re.finditer(rf"<{tag}\b[^>]*\b{attr}\s*=\s*['\"]([^'\"]+)", html, re.I):
            assert not re.match(r"^(https?:)?//", m.group(1)), f"external {tag}: {m.group(1)}"
    assert "@import" not in html
    assert not re.search(r"url\(\s*['\"]?(https?:)?//", html)
    assert "<link" not in html.lower()


def test_disclaimer_cutoff_and_levels(data):
    html = _html(data)
    assert "AI 產生之草稿" in html and "流行病學專業人員審閱" in html
    assert "資料截止" in html and "2026-11-19 11:10" in html
    assert "試算" in html and "非正式" in html
    assert "將視新增實證適時調整" in html
    # level badges always carry an icon and a text label
    assert re.search(r'class="lv lv-low[^"]*"><svg class="ic"[^>]*><use href="#lvicon-low"/></svg><span>低</span>', html)


def test_payload_matrix_matches_python(data):
    html = _html(data)
    m = re.search(r'<script type="application/json" id="report-data">(.*?)</script>', html, re.S)
    payload = json.loads(m.group(1))
    assert payload["matrix"] == {str(p): {str(i): RISK_MATRIX[p][i] for i in RISK_MATRIX[p]} for p in RISK_MATRIX}
    assert [it["id"] for it in payload["items"]] == ["R1", "R2", "R3", "R4"]


def test_references_numbered_and_linked(data):
    html = _html(data)
    assert 'id="ref-S2"' in html
    assert 'href="https://www.who.int/emergencies/disease-outbreak-news/item/2026-DON626"' in html
    assert 'href="#ref-S2"' in html


def test_untrusted_text_is_escaped(data):
    evil = '</script><script>alert(1)</script><img src=x onerror=alert(2)>'
    data["risk_items"][0]["name"] = evil
    data["claims"][0]["text"] = evil
    html = _html(data)
    assert "<script>alert(1)</script>" not in html
    assert "<img src=x" not in html
    # the JSON payload must not be able to close its <script> element
    payload = re.search(r'<script type="application/json" id="report-data">(.*?)</script>', html, re.S).group(1)
    assert "</" not in payload
    assert json.loads(payload)["items"][0]["name"] == evil


def test_uncited_and_mismatch_are_visible(data):
    data["risk_items"][0]["proposed_level"] = "高"
    html = _html(data)
    assert "未引證" in html
    assert "評估者建議「高」" in html


def test_optional_charts(data):
    data["international"]["time_series"] = [{"date": "2026-10-01", "value": 3, "series": "病例數"},
                                            {"date": "2026-10-08", "value": 5, "series": "病例數"}]
    html = _html(data)
    assert 'id="tsChart"' in html
    data["international"]["time_series"] = []
    data["international"]["country_counts"] = []
    html = _html(data)
    assert 'id="tsChart"' not in html and "各國病例數" not in html
