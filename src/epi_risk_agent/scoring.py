"""Deterministic combination and validation rules.

Nothing in here calls an LLM. Given an ``Assessment`` (LLM judgments with
citations), ``audit()`` recomputes every derived quantity and lists every rule
violation as an ``Issue``. The proposed (LLM) levels are *compared* with the
computed ones; disagreements are surfaced, never silently overwritten.

See docs/methodology.md for the rationale of each rule and table.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Optional

from .schema import (
    Assessment,
    Audit,
    Claim,
    ClaimAudit,
    Issue,
    ItemAudit,
    RiskItem,
    Source,
)

MATRIX_VERSION = "epi-risk-5x5-v1"

P_LABELS = {1: "極低", 2: "低", 3: "中", 4: "高", 5: "極高"}
I_LABELS = {1: "極低", 2: "低", 3: "中", 4: "高", 5: "極高"}

# Risk-ranking matrix: rows = probability 1..5, columns = impact 1..5.
# Written out explicitly (not as a formula) so it can be audited and edited.
# It equals banding the product P*I as <=4 低, 5-9 中, 10-15 高, >=16 極高;
# test_scoring.py checks both the table and its symmetry.
RISK_MATRIX: dict[int, dict[int, str]] = {
    1: {1: "低", 2: "低", 3: "低", 4: "低", 5: "中"},
    2: {1: "低", 2: "低", 3: "中", 4: "中", 5: "高"},
    3: {1: "低", 2: "中", 3: "中", 4: "高", 5: "高"},
    4: {1: "低", 2: "中", 3: "高", 4: "極高", 5: "極高"},
    5: {1: "中", 2: "高", 3: "高", 4: "極高", 5: "極高"},
}

# 4-level matrix output -> 3-level scale used by the Taiwan CDC articles.
MATRIX_TO_LEVEL3 = {"低": "低", "中": "中", "高": "高", "極高": "高"}

# Item-level 評估結果 (as in the Taiwan CDC article tables): probability items
# show the probability of occurrence alone, the 衝擊 row shows impact alone.
PROBABILITY_TO_LEVEL3 = {1: "低", 2: "低", 3: "中", 4: "高", 5: "高"}
IMPACT_TO_LEVEL3 = {1: "低", 2: "低", 3: "中", 4: "高", 5: "高"}

LEVEL3_ORDER = {"低": 0, "中": 1, "高": 2}
MATRIX_ORDER = {"低": 0, "中": 1, "高": 2, "極高": 3}
CONF_ORDER = {"低": 0, "中": 1, "高": 2}

TIER_LABELS = {1: "官方衛生機關/國際組織", 2: "同儕審查文獻", 3: "主流媒體", 4: "社群/未知"}

REQUIRED_SCENARIOS = ("最佳", "最可能", "最壞")


def matrix_level(p: int, i: int) -> str:
    if p not in RISK_MATRIX or i not in RISK_MATRIX[p]:
        raise ValueError(f"probability/impact must be 1..5, got P={p}, I={i}")
    return RISK_MATRIX[p][i]


def level3_from_matrix(level: str) -> str:
    return MATRIX_TO_LEVEL3[level]


def level3_from_probability(p: int) -> str:
    return PROBABILITY_TO_LEVEL3[p]


def level3_from_impact(i: int) -> str:
    return IMPACT_TO_LEVEL3[i]


def _min_conf(a: str, b: str) -> str:
    return a if CONF_ORDER[a] <= CONF_ORDER[b] else b


def _parse_dt(s: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _parse_date(s: str) -> Optional[date]:
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Source reference collection
# ---------------------------------------------------------------------------


def iter_source_refs(a: Assessment) -> Iterable[tuple[str, str]]:
    """Yield (path, source_id) for every citation in the document."""
    yield "event.news_source_id", a.event.news_source_id
    for c in a.claims:
        for k, e in enumerate(c.evidence):
            yield f"claims[{c.id}].evidence[{k}]", e.source_id
    for k, f in enumerate(a.pathogen.facts):
        for sid in f.source_ids:
            yield f"pathogen.facts[{k}]", sid
    intl = a.international
    for group, items in (
        ("international.summary", intl.summary),
        ("international.external_assessments", intl.external_assessments),
        ("international.stats", intl.stats),
        ("international.timeline", intl.timeline),
        ("international.country_counts", intl.country_counts),
    ):
        for k, it in enumerate(items):
            for sid in it.source_ids:
                yield f"{group}[{k}]", sid
    for group in ("surveillance", "laboratory", "vectors_hosts", "border_travel", "healthcare"):
        for k, b in enumerate(getattr(a.taiwan, group)):
            for sid in b.source_ids:
                yield f"taiwan.{group}[{k}]", sid
    for r in a.risk_items:
        for k, b in enumerate(r.evidence):
            for sid in b.source_ids:
                yield f"risk_items[{r.id}].evidence[{k}]", sid
        for k, h in enumerate(r.hairs_questions):
            for sid in h.source_ids:
                yield f"risk_items[{r.id}].hairs_questions[{k}]", sid
    for q in a.ihr_annex2.questions:
        for sid in q.source_ids:
            yield f"ihr_annex2.{q.key}", sid
    for rec in a.recommendations:
        for sid in rec.source_ids:
            yield f"recommendations[{rec.id}]", sid


def all_evidence_bullets(a: Assessment):
    for b in a.international.summary:
        yield "international.summary", b
    for b in a.international.external_assessments:
        yield "international.external_assessments", b
    for group in ("surveillance", "laboratory", "vectors_hosts", "border_travel", "healthcare"):
        for b in getattr(a.taiwan, group):
            yield f"taiwan.{group}", b
    for r in a.risk_items:
        for b in r.evidence:
            yield f"risk_items[{r.id}]", b


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------


def _independent(src: Source, news: Optional[Source]) -> bool:
    if src.url is None or src.is_news_item or src.retrieval == "未取得":
        return False
    if news is not None:
        if src.id == news.id:
            return False
        if src.publisher.strip().lower() == news.publisher.strip().lower():
            return False
        if news.url and src.url and news.url.rstrip("/") == src.url.rstrip("/"):
            return False
    return True


def audit_claim(c: Claim, sources: dict[str, Source], news: Optional[Source]) -> ClaimAudit:
    support = [sources[e.source_id] for e in c.evidence if e.stance == "支持" and e.source_id in sources]
    contra = [sources[e.source_id] for e in c.evidence if e.stance == "反駁" and e.source_id in sources]
    any_ev = [sources[e.source_id] for e in c.evidence if e.source_id in sources]
    indep_support = {s.id: s for s in support if _independent(s, news)}
    indep_contra = {s.id: s for s in contra if _independent(s, news)}
    reasons: list[str] = []
    passes = True
    suggested = None
    best_tier = min((s.tier for s in indep_support.values()), default=None)

    if c.verdict in ("已證實", "部分證實"):
        if not indep_support:
            passes = False
            suggested = "無法證實"
            reasons.append("缺少至少 1 個「具網址、且與新聞不同發布者」之支持來源")
        elif c.verdict == "已證實" and best_tier is not None and best_tier >= 3:
            reasons.append("已證實僅由媒體或未知來源支持；建議以官方或文獻來源再確認")
        if indep_support and all(s.retrieval == "搜尋摘要" for s in indep_support.values()):
            reasons.append("支持來源僅取得搜尋摘要，未讀取全文")
    elif c.verdict == "與官方資訊不符":
        tier1 = [s for s in indep_contra.values() if s.tier == 1]
        if not tier1:
            passes = False
            suggested = "無法證實"
            reasons.append("判定「與官方資訊不符」需至少 1 個官方（第 1 級）反駁來源")
    elif c.verdict == "過時":
        if not any(s.url for s in any_ev):
            passes = False
            suggested = "無法證實"
            reasons.append("判定「過時」需至少 1 個具網址之較新來源")
    if indep_support and indep_contra:
        reasons.append("支持與反駁來源並存，請於說明中交代衝突")
    return ClaimAudit(
        claim_id=c.id,
        stated_verdict=c.verdict,
        passes_rules=passes,
        suggested_verdict=suggested,
        independent_sources=len(indep_support) + len(indep_contra),
        best_tier=best_tier,
        reasons=reasons,
    )


VERDICT_SCORE = {"已證實": 1.0, "部分證實": 0.6, "過時": 0.4, "無法證實": 0.25, "與官方資訊不符": 0.0}


def credibility(claims: list[Claim], claim_audits: list[ClaimAudit], news: Optional[Source]) -> tuple[str, str]:
    audits = {ca.claim_id: ca for ca in claim_audits}
    key = [c for c in claims if c.importance == "關鍵"] or list(claims)
    if not key:
        return "低", "新聞未擷取出可查證之陳述"
    effective = []
    for c in key:
        ca = audits[c.id]
        effective.append(ca.suggested_verdict if not ca.passes_rules and ca.suggested_verdict else c.verdict)
    if "與官方資訊不符" in effective:
        level = "低"
        why = "至少一項關鍵陳述與官方資訊不符"
    else:
        score = sum(VERDICT_SCORE[v] for v in effective) / len(effective)
        level = "高" if score >= 0.8 else ("中" if score >= 0.5 else "低")
        why = f"關鍵陳述平均查證分數 {score:.2f}（已證實=1、部分證實=0.6、過時=0.4、無法證實=0.25、不符=0）"
    if news is not None and news.tier == 4 and level == "高":
        level = "中"
        why += "；新聞來源屬社群/未知等級，上限為「中」"
    return level, why


# ---------------------------------------------------------------------------
# Risk items
# ---------------------------------------------------------------------------


def _item_sources(item: RiskItem, sources: dict[str, Source]) -> list[Source]:
    ids = []
    for b in item.evidence:
        for sid in b.source_ids:
            if sid in sources and sid not in ids:
                ids.append(sid)
    return [sources[i] for i in ids]


def confidence_caps(item: RiskItem, sources: dict[str, Source]) -> tuple[str, list[str], int]:
    """Return (effective confidence, cap reasons, uncited bullet count)."""
    eff = item.confidence
    caps: list[str] = []
    cited = _item_sources(item, sources)
    non_news = [s for s in cited if not s.is_news_item]
    uncited = sum(1 for b in item.evidence if not b.source_ids)
    if not cited:
        eff = _min_conf(eff, "低")
        caps.append("評估內容皆未引證 → 上限「低」")
    else:
        if len({s.publisher for s in non_news}) <= 1:
            eff = _min_conf(eff, "中")
            caps.append("僅單一發布者之來源 → 上限「中」")
        if min(s.tier for s in cited) >= 3:
            eff = _min_conf(eff, "低")
            caps.append("無官方或文獻等級來源（僅媒體/未知）→ 上限「低」")
        if all(s.retrieval != "全文" for s in cited):
            eff = _min_conf(eff, "中")
            caps.append("所有來源僅取得搜尋摘要或未取得全文 → 上限「中」")
    if item.evidence and uncited / len(item.evidence) > 0.3:
        eff = _min_conf(eff, "中")
        caps.append(f"{uncited}/{len(item.evidence)} 則評估內容未引證（>30%）→ 上限「中」")
    return eff, caps, uncited


def audit_items(a: Assessment, sources: dict[str, Source]) -> tuple[list[ItemAudit], Optional[int]]:
    impact_items = [r for r in a.risk_items if r.kind == "衝擊"]
    shared_impact = max((r.impact for r in impact_items if r.impact is not None), default=None)
    out: list[ItemAudit] = []
    for r in a.risk_items:
        eff, caps, uncited = confidence_caps(r, sources)
        strata_out: list[dict] = []
        if r.kind == "機率":
            # Article convention: a probability item's 評估結果 is the probability
            # of occurrence alone; P x I is reported separately as 矩陣風險.
            p = r.probability
            i = r.impact if r.impact is not None else shared_impact
            inherited = r.impact is None
            mlev = matrix_level(p, i) if (p is not None and i is not None) else None
            comp = level3_from_probability(p)
            for s in r.strata:
                sp = s.probability or p
                si = s.impact or i
                st = {"name": s.name, "probability": sp, "impact": si, "computed_level": level3_from_probability(sp),
                      "proposed_level": s.proposed_level, "matrix_level": None, "matrix_level3": None}
                if sp and si:
                    st["matrix_level"] = matrix_level(sp, si)
                    st["matrix_level3"] = level3_from_matrix(st["matrix_level"])
                strata_out.append(st)
        else:
            p = None
            i = r.impact
            inherited = False
            mlev = None
            comp = level3_from_impact(i)
            for s in r.strata:
                si = s.impact or i
                strata_out.append({"name": s.name, "impact": si, "computed_level": level3_from_impact(si),
                                   "proposed_level": s.proposed_level})
        out.append(ItemAudit(
            item_id=r.id, probability=p, impact=i, impact_inherited=inherited, matrix_level=mlev,
            matrix_level3=level3_from_matrix(mlev) if mlev else None,
            computed_level=comp, proposed_level=r.proposed_level, agrees=(comp == r.proposed_level),
            stated_confidence=r.confidence, effective_confidence=eff, confidence_caps=caps,
            uncited_bullets=uncited, strata_computed=strata_out,
        ))
    return out, shared_impact


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def audit(a: Assessment) -> Audit:
    issues: list[Issue] = []
    sources = {s.id: s for s in a.sources}
    news = sources.get(a.event.news_source_id)

    # --- referential integrity -------------------------------------------
    used: set[str] = set()
    for path, sid in iter_source_refs(a):
        used.add(sid)
        if sid not in sources:
            issues.append(Issue(severity="error", code="unknown_source", message=f"引用了不存在的來源代碼 {sid}", path=path))
    if news is None:
        issues.append(Issue(severity="error", code="news_source_missing", message="event.news_source_id 未對應任何來源"))
    elif not news.is_news_item:
        issues.append(Issue(severity="warning", code="news_flag", message=f"{news.id} 應標記 is_news_item=true"))
    for s in a.sources:
        if s.id not in used:
            issues.append(Issue(severity="info", code="unused_source", message=f"來源 {s.id} 未被引用", path=f"sources[{s.id}]"))
        if s.url is None and s.retrieval != "未取得" and not s.is_news_item:
            issues.append(Issue(severity="warning", code="source_no_url", message=f"來源 {s.id} 無網址卻標示為已取得", path=f"sources[{s.id}]"))
        if s.retrieval != "未取得" and not s.accessed_date:
            issues.append(Issue(severity="warning", code="source_no_access_date", message=f"來源 {s.id} 缺取用日期", path=f"sources[{s.id}]"))

    # --- uncited evidence --------------------------------------------------
    for path, b in all_evidence_bullets(a):
        if not b.source_ids:
            issues.append(Issue(severity="warning", code="uncited", message=f"未引證：「{b.text[:40]}…」", path=path))

    # --- claims -------------------------------------------------------------
    claim_audits = [audit_claim(c, sources, news) for c in a.claims]
    for ca in claim_audits:
        if not ca.passes_rules:
            issues.append(Issue(severity="error", code="claim_rule",
                                message=f"陳述 {ca.claim_id} 判定「{ca.stated_verdict}」未通過查證規則：{'；'.join(ca.reasons)}；依規則應為「{ca.suggested_verdict}」",
                                path=f"claims[{ca.claim_id}]"))
        elif ca.reasons:
            issues.append(Issue(severity="warning", code="claim_caution", message=f"陳述 {ca.claim_id}：{'；'.join(ca.reasons)}", path=f"claims[{ca.claim_id}]"))
    if not a.claims:
        issues.append(Issue(severity="warning", code="no_claims", message="未擷取任何可查證陳述"))
    cred_level, cred_reason = credibility(a.claims, claim_audits, news)
    if cred_level != a.news_credibility.proposed_level:
        issues.append(Issue(severity="warning", code="credibility_mismatch",
                            message=f"新聞可信度：評估者建議「{a.news_credibility.proposed_level}」，規則計算「{cred_level}」"))

    # --- risk items ---------------------------------------------------------
    item_audits, shared_impact = audit_items(a, sources)
    names = {r.id: r.name for r in a.risk_items}
    for ia in item_audits:
        if not ia.agrees:
            issues.append(Issue(severity="warning", code="level_mismatch",
                                message=f"{names[ia.item_id]}：評估者建議「{ia.proposed_level}」，規則對應「{ia.computed_level}」（{'機率' if ia.probability is not None else '衝擊'} {ia.probability if ia.probability is not None else ia.impact}）",
                                path=f"risk_items[{ia.item_id}]"))
        if ia.effective_confidence != ia.stated_confidence:
            issues.append(Issue(severity="info", code="confidence_capped",
                                message=f"{names[ia.item_id]}：信心程度由「{ia.stated_confidence}」調降為「{ia.effective_confidence}」（{'；'.join(ia.confidence_caps)}）",
                                path=f"risk_items[{ia.item_id}]"))
        for st in ia.strata_computed:
            if st.get("computed_level") and st["computed_level"] != st["proposed_level"]:
                issues.append(Issue(severity="warning", code="stratum_mismatch",
                                    message=f"{names[ia.item_id]}／{st['name']}：建議「{st['proposed_level']}」，計算「{st['computed_level']}」",
                                    path=f"risk_items[{ia.item_id}]"))
    prob_audits = [ia for ia in item_audits if ia.matrix_level is not None]
    if prob_audits:
        driver = max(prob_audits, key=lambda ia: (MATRIX_ORDER[ia.matrix_level], ia.probability or 0))
        overall_m = driver.matrix_level
        overall_p = driver.probability
        overall_i = driver.impact
        overall_from = driver.item_id
        overall_comp = level3_from_matrix(overall_m)
    else:  # pragma: no cover - schema guarantees a probability item
        overall_m = overall_p = overall_i = overall_from = None
        overall_comp = a.overall.proposed_level
    overall_agrees = overall_comp == a.overall.proposed_level
    for ia in item_audits:
        for st in ia.strata_computed:
            m3 = st.get("matrix_level3")
            if m3 and LEVEL3_ORDER[m3] > LEVEL3_ORDER[overall_comp]:
                issues.append(Issue(severity="info", code="stratum_higher",
                                    message=f"{names[ia.item_id]}：分層「{st['name']}」之矩陣風險（{st['matrix_level']}→{m3}）高於整體（{overall_comp}），決策摘要應明列",
                                    path=f"risk_items[{ia.item_id}]"))
    if not overall_agrees:
        issues.append(Issue(severity="warning", code="overall_mismatch",
                            message=f"綜合研判：評估者建議「{a.overall.proposed_level}」，矩陣計算「{overall_comp}」（取最高之機率項目 {overall_from}）"))

    overall_conf = "高"
    overall_caps: list[str] = []
    for ia in item_audits:
        if CONF_ORDER[ia.effective_confidence] < CONF_ORDER[overall_conf]:
            overall_conf = ia.effective_confidence
            overall_caps = [f"受「{names[ia.item_id]}」信心程度「{ia.effective_confidence}」限制"]
    key_claims = [c for c in a.claims if c.importance == "關鍵"]
    failing_key = [ca for ca in claim_audits if not ca.passes_rules and ca.claim_id in {c.id for c in key_claims}]
    if failing_key:
        overall_conf = _min_conf(overall_conf, "中")
        overall_caps.append("有關鍵陳述未通過查證規則 → 上限「中」")

    # --- IHR Annex 2 --------------------------------------------------------
    yes = sum(1 for q in a.ihr_annex2.questions if q.answer == "是")
    unk = sum(1 for q in a.ihr_annex2.questions if q.answer == "不確定")
    meets = yes >= 2 or a.ihr_annex2.always_notifiable_disease
    if a.ihr_annex2.always_notifiable_disease:
        note = "屬附件二所列一律通報之疾病，不論四問題結果皆應通報"
    elif meets:
        note = f"四問題中 {yes} 項為「是」（≥2），符合附件二通報門檻"
    elif yes + unk >= 2:
        note = f"目前 {yes} 項「是」、{unk} 項「不確定」；若不確定項目轉為「是」即達門檻，應持續追蹤"
    else:
        note = f"四問題中 {yes} 項為「是」（<2），未達附件二通報門檻"

    # --- structural / decision support checks ------------------------------
    kinds = {s.kind for s in a.scenarios}
    for k in REQUIRED_SCENARIOS:
        if k not in kinds:
            issues.append(Issue(severity="warning", code="scenario_missing", message=f"缺少「{k}」情境"))
    rec_opts = [o for o in a.decision.options if o.recommended]
    if not rec_opts:
        issues.append(Issue(severity="error", code="no_recommended_option", message="決策選項中沒有標記建議方案"))
    elif len(rec_opts) > 1:
        issues.append(Issue(severity="warning", code="multiple_recommended", message="有多個決策選項標記為建議方案"))
    if len(a.decision.options) < 2:
        issues.append(Issue(severity="warning", code="few_options", message="決策選項少於 2 個，無法比較"))
    dirs = {t.direction for t in a.decision.triggers}
    for d in ("升級", "降級"):
        if d not in dirs:
            issues.append(Issue(severity="warning", code="trigger_missing", message=f"缺少「{d}」觸發指標"))
    if not a.recommendations:
        issues.append(Issue(severity="error", code="no_recommendations", message="沒有建議事項"))
    for cat in ("監測通報", "風險溝通"):
        if cat not in {r.category for r in a.recommendations}:
            issues.append(Issue(severity="info", code="rec_category_missing", message=f"建議事項未涵蓋「{cat}」"))
    n_find = len(a.overall.key_findings)
    if not 3 <= n_find <= 5:
        issues.append(Issue(severity="warning", code="key_findings_count", message=f"重點發現應為 3–5 項（目前 {n_find}）"))
    if not a.limitations:
        issues.append(Issue(severity="warning", code="no_limitations", message="未陳述限制與不確定性"))
    if any(t in a.event.event_type for t in ("人畜共通", "新興或不明病原")):
        if not any(r.hairs_questions for r in a.risk_items):
            issues.append(Issue(severity="info", code="hairs_missing", message="人畜共通/新興事件建議填寫 HAIRS 式篩檢問題"))

    gen = _parse_dt(a.generated_at)
    cutoff = _parse_dt(a.data_cutoff)
    reass = _parse_date(a.reassessment_date)
    if gen is None:
        issues.append(Issue(severity="warning", code="bad_date", message="generated_at 非 ISO 8601"))
    if cutoff is None:
        issues.append(Issue(severity="warning", code="bad_date", message="data_cutoff 非 ISO 8601"))
    if reass is None:
        issues.append(Issue(severity="warning", code="bad_date", message="reassessment_date 非 YYYY-MM-DD"))
    elif gen is not None and reass <= gen.date():
        issues.append(Issue(severity="warning", code="reassessment_past", message="再評估日期應晚於產出日期"))
    if gen and cutoff and cutoff > gen:
        issues.append(Issue(severity="warning", code="cutoff_after_generation", message="資料截止時間晚於產出時間"))
    for s in a.sources:
        if s.published_date and cutoff and _parse_date(s.published_date) and _parse_date(s.published_date) > cutoff.date():
            issues.append(Issue(severity="warning", code="source_after_cutoff", message=f"來源 {s.id} 發布日期晚於資料截止時間"))

    return Audit(
        matrix_version=MATRIX_VERSION,
        items=item_audits,
        overall_probability=overall_p,
        overall_probability_from=overall_from,
        overall_impact=overall_i,
        overall_matrix_level=overall_m,
        overall_computed_level=overall_comp,
        overall_proposed_level=a.overall.proposed_level,
        overall_agrees=overall_agrees,
        overall_confidence=overall_conf,
        overall_confidence_caps=overall_caps,
        claims=claim_audits,
        credibility_computed=cred_level,
        credibility_proposed=a.news_credibility.proposed_level,
        credibility_reason=cred_reason,
        ihr_yes_count=yes,
        ihr_unknown_count=unk,
        ihr_meets_threshold=meets,
        ihr_note=note,
        issues=issues,
    )


def apply_audit(a: Assessment) -> Assessment:
    """Return a copy of ``a`` with ``audit`` recomputed (input audit ignored)."""
    clean = a.model_copy(update={"audit": None})
    return clean.model_copy(update={"audit": audit(clean)})


def error_count(au: Audit) -> int:
    return sum(1 for i in au.issues if i.severity == "error")
