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


def test_matrix_laid_out_like_ecdc_figure4(data):
    html = _html(data)
    m = re.search(r'<table class="matrix"[^>]*>(.*?)</table>', html, re.S).group(1)
    heads = re.findall(r'<th scope="col">(\d)<span class="ax">([^<]+)</span>', m)
    assert heads == [("0", "無"), ("1", "極低"), ("2", "低"), ("3", "中"), ("4", "高")]
    rows = re.findall(r'<th scope="row">(\d)<span class="ax">([^<]+)</span>', m)
    assert rows == [("1", "極低"), ("2", "低"), ("3", "中"), ("4", "高")]
    first_row = re.findall(r'<span class="cell-lv">([^<]+)</span>', m)[:5]
    assert first_row == ["無", "極低", "低", "低", "中"]  # impact Very low row of Figure 4
    for lv, cls in (("無", "none"), ("極低", "vlow"), ("極高", "vhigh")):
        assert f'<use href="#lvicon-{cls}"/></svg><span>{lv}</span>' in html


def test_ecdc_paths_and_hairs_crosscheck_shown(data):
    html = _html(data)
    assert "ECDC 圖 2.2：Q2 否 ⇒ 極低" in html
    assert "ECDC 圖 3：Q5 是 → Q6 否 ⇒ 低" in html
    assert "交叉核對：UKHSA HAIRS 演算法（不併入矩陣）" in html
    assert "尚可" in html  # Box 2 / Appendix B wording for confidence 中


def test_measles_example_renders_cleanly():
    from pathlib import Path

    from epi_risk_agent.scoring import apply_audit

    p = Path(__file__).resolve().parents[1] / "examples" / "us-measles-pregnancy-2026" / "assessment.json"
    a = Assessment.model_validate(json.loads(p.read_text(encoding="utf-8")))
    au = apply_audit(a).audit
    assert au.overall_computed_level == "低" and au.overall_agrees
    assert sum(1 for i in au.issues if i.severity == "error") == 0
    html = render_html(a)
    assert "交叉核對：UKHSA HAIRS" not in html  # not zoonotic, no HAIRS block
    assert not re.search(r"<script\b[^>]*\bsrc=", html)


def test_who_and_synthesis_sections(data):
    html = _html(data)
    assert "並行評估：WHO 2012 風險矩陣" in html and "評估者依其表 7、表 8 定義之判斷" in html
    assert "綜合評估：各架構結果比較" in html
    assert "ECDC 低｜WHO 中｜HAIRS 機率中・衝擊中｜文章式判斷 低｜審慎上限 中" in html
    assert html.index('id="synthesis-h"') < html.index('id="sec-scenario"')  # last part of section 5
    assert "評估者說明：" in html
    m = re.search(r'<table class="matrix who-matrix".*?</table>', html, re.S).group(0)
    assert m.count('<th scope="row">') == 5 and '<span class="marker static" title="一般民眾">W</span>' in m
