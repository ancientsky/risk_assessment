"""assessment JSON -> ONE self-contained HTML report (no external requests).

All CSS, JS and icons are inlined; the risk matrix table and level mappings are
exported from ``scoring.py`` into the page so the in-browser what-if calculator
uses exactly the same rules as the official computation.
"""

from __future__ import annotations

import json
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, select_autoescape
from markupsafe import Markup, escape

from . import METHODOLOGY_VERSION, __version__
from .schema import Assessment
from .scoring import (
    I_LABELS,
    IMPACT_TO_LEVEL3,
    MATRIX_TO_LEVEL3,
    MATRIX_VERSION,
    P_LABELS,
    RISK_MATRIX,
    TIER_LABELS,
    apply_audit,
)

LEVEL_CLASS = {"低": "low", "中": "mod", "高": "high", "極高": "vhigh"}
VERDICT_CLASS = {"已證實": "ok", "部分證實": "partial", "無法證實": "unk", "與官方資訊不符": "bad", "過時": "old"}
VERDICT_ICON = {"已證實": "i-check", "部分證實": "i-half", "無法證實": "i-question", "與官方資訊不符": "i-cross", "過時": "i-clock"}
STANCE_CLASS = {"支持": "sup", "反駁": "con", "背景": "ctx"}
IHR_LABELS = {
    "serious_impact": "一、事件對公共衛生的影響是否嚴重？",
    "unusual_unexpected": "二、事件是否不尋常或非預期？",
    "international_spread": "三、是否有國際傳播的顯著風險？",
    "travel_trade_restriction": "四、是否有限制國際旅行或貿易的顯著風險？",
}
SCENARIO_ORDER = {"最佳": 0, "最可能": 1, "最壞": 2}


def _read_template(name: str) -> str:
    return resources.files("epi_risk_agent").joinpath("templates", name).read_text(encoding="utf-8")


def _json_for_script(obj: Any) -> Markup:
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    s = s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    s = s.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return Markup(s)


def _fmt_dt(s: Optional[str]) -> str:
    if not s:
        return "—"
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        tz = d.strftime("%z")
        tzs = f"（UTC{tz[:3]}:{tz[3:]}）" if tz else ""
        return d.strftime("%Y-%m-%d %H:%M") + tzs
    except ValueError:
        return s


def build_context(a: Assessment) -> dict[str, Any]:
    a = apply_audit(a)
    au = a.audit
    assert au is not None
    src_num = {s.id: n for n, s in enumerate(a.sources, start=1)}
    src_by_id = {s.id: s for s in a.sources}

    def cite(ids: list[str]) -> Markup:
        if not ids:
            return Markup('<span class="chip chip-uncited" title="此項評估內容未引用任何來源">未引證</span>')
        parts = []
        for sid in ids:
            n = src_num.get(sid)
            if n is None:
                parts.append(f'<span class="chip chip-uncited" title="來源代碼不存在">{escape(sid)}?</span>')
            else:
                s = src_by_id[sid]
                tip = escape(f"{s.publisher}：{s.title}")
                parts.append(f'<a class="cite" href="#ref-{escape(sid)}" title="{tip}">[{n}]</a>')
        return Markup('<span class="cites">' + "".join(parts) + "</span>")

    def level_badge(level: Optional[str], size: str = "") -> Markup:
        if not level:
            return Markup('<span class="lv lv-na">—</span>')
        cls = LEVEL_CLASS[level]
        return Markup(
            f'<span class="lv lv-{cls} {size}"><svg class="ic" aria-hidden="true"><use href="#lvicon-{cls}"/></svg>'
            f"<span>{escape(level)}</span></span>"
        )

    def verdict_chip(v: str) -> Markup:
        return Markup(
            f'<span class="vd vd-{VERDICT_CLASS[v]}"><svg class="ic" aria-hidden="true"><use href="#{VERDICT_ICON[v]}"/></svg>'
            f"{escape(v)}</span>"
        )

    item_audit = {ia.item_id: ia for ia in au.items}
    claim_audit = {ca.claim_id: ca for ca in au.claims}
    items_view = []
    for idx, r in enumerate(a.risk_items, start=1):
        ia = item_audit[r.id]
        items_view.append({"item": r, "audit": ia, "n": idx})

    rec_option = next((o for o in a.decision.options if o.recommended), None)
    higher_strata = []
    for iv in items_view:
        if iv["item"].kind != "機率":  # impact strata are consequence levels, not risk levels
            continue
        for st in iv["audit"].strata_computed:
            lvl = st.get("computed_level") or st.get("proposed_level")
            if lvl and {"低": 0, "中": 1, "高": 2}[lvl] > {"低": 0, "中": 1, "高": 2}[au.overall_computed_level]:
                higher_strata.append({"item": iv["item"].name, "name": st["name"], "level": lvl})

    # chart data -------------------------------------------------------------
    cc = [c for c in a.international.country_counts if c.cases is not None]
    max_cases = max((c.cases for c in cc), default=0) or 1
    country_bars = [{"c": c, "pct": max(0.5, 100.0 * c.cases / max_cases)} for c in sorted(cc, key=lambda x: -x.cases)]

    payload = {
        "matrix": {str(p): {str(i): RISK_MATRIX[p][i] for i in RISK_MATRIX[p]} for p in RISK_MATRIX},
        "matrixTo3": MATRIX_TO_LEVEL3,
        "impactTo3": {str(k): v for k, v in IMPACT_TO_LEVEL3.items()},
        "pLabels": {str(k): v for k, v in P_LABELS.items()},
        "iLabels": {str(k): v for k, v in I_LABELS.items()},
        "levelClass": LEVEL_CLASS,
        "items": [
            {
                "id": iv["item"].id,
                "n": iv["n"],
                "name": iv["item"].name,
                "kind": iv["item"].kind,
                "p": iv["item"].probability,
                "i": iv["item"].impact,
                "inherit": iv["audit"].impact_inherited,
                "computed": iv["audit"].computed_level,
                "matrix": iv["audit"].matrix_level,
                "proposed": iv["item"].proposed_level,
                "confidence": iv["audit"].effective_confidence,
            }
            for iv in items_view
        ],
        "overall": {"computed": au.overall_computed_level, "matrix": au.overall_matrix_level,
                    "p": au.overall_probability, "i": au.overall_impact, "from": au.overall_probability_from},
        "timeseries": [p.model_dump() for p in a.international.time_series],
    }

    issues_sorted = sorted(au.issues, key=lambda x: {"error": 0, "warning": 1, "info": 2}[x.severity])
    return {
        "a": a,
        "au": au,
        "cite": cite,
        "level_badge": level_badge,
        "verdict_chip": verdict_chip,
        "items_view": items_view,
        "item_audit": item_audit,
        "claim_audit": claim_audit,
        "rec_option": rec_option,
        "higher_strata": higher_strata,
        "country_bars": country_bars,
        "scenarios": sorted(a.scenarios, key=lambda s: SCENARIO_ORDER[s.kind]),
        "ihr_labels": IHR_LABELS,
        "src_num": src_num,
        "src_by_id": src_by_id,
        "tier_labels": TIER_LABELS,
        "p_labels": P_LABELS,
        "i_labels": I_LABELS,
        "matrix": RISK_MATRIX,
        "level_class": LEVEL_CLASS,
        "stance_class": STANCE_CLASS,
        "issues": issues_sorted,
        "n_err": sum(1 for i in au.issues if i.severity == "error"),
        "n_warn": sum(1 for i in au.issues if i.severity == "warning"),
        "payload": _json_for_script(payload),
        "fmt_dt": _fmt_dt,
        "rec_categories": sorted({r.category for r in a.recommendations}, key=lambda c: [r.category for r in a.recommendations].index(c)),
        "tool_version": __version__,
        "methodology_version": METHODOLOGY_VERSION,
        "matrix_version": MATRIX_VERSION,
        "css": Markup(_read_template("report.css")),
        "js": Markup(_read_template("report.js")),
    }


def render_html(a: Assessment) -> str:
    env = Environment(autoescape=select_autoescape(default=True, default_for_string=True), trim_blocks=True, lstrip_blocks=True)
    tpl = env.from_string(_read_template("report.html"))
    return tpl.render(**build_context(a))


def load_assessment(path: str | Path) -> Assessment:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Assessment.model_validate(data)


def render_file(in_path: str | Path, out_path: str | Path) -> Assessment:
    a = load_assessment(in_path)
    html = render_html(a)
    Path(out_path).write_text(html, encoding="utf-8")
    return a
