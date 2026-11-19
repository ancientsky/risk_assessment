import pytest
from pydantic import ValidationError

from epi_risk_agent.schema import Assessment
from epi_risk_agent.scoring import (
    IMPACT_TO_LEVEL3,
    PROBABILITY_TO_LEVEL3,
    MATRIX_TO_LEVEL3,
    RISK_MATRIX,
    apply_audit,
    audit,
    matrix_level,
)


# ECDC (2019) Figure 4, transcribed from the published figure (rows = impact,
# columns = probability None, Very low, Low, Moderate, High).
FIG4 = {
    1: ["無", "極低", "低", "低", "中"],     # impact Very low
    2: ["無", "低", "低", "中", "中"],       # impact Low
    3: ["無", "低", "中", "中", "高"],       # impact Moderate
    4: ["無", "中", "中", "高", "極高"],     # impact High
}


@pytest.mark.parametrize("p", range(0, 5))
@pytest.mark.parametrize("i", range(1, 5))
def test_matrix_equals_ecdc_figure4(p, i):
    assert RISK_MATRIX[p][i] == FIG4[i][p]
    assert matrix_level(p, i) == FIG4[i][p]


def test_matrix_has_exactly_20_cells():
    assert sorted(RISK_MATRIX) == [0, 1, 2, 3, 4]
    assert all(sorted(RISK_MATRIX[p]) == [1, 2, 3, 4] for p in RISK_MATRIX)


def test_matrix_monotonic():
    order = {"無": 0, "極低": 1, "低": 2, "中": 3, "高": 4, "極高": 5}
    for p in range(0, 5):
        for i in range(1, 4):
            assert order[RISK_MATRIX[p][i]] <= order[RISK_MATRIX[p][i + 1]]
    for i in range(1, 5):
        for p in range(0, 4):
            assert order[RISK_MATRIX[p][i]] <= order[RISK_MATRIX[p + 1][i]]


@pytest.mark.parametrize("p,i", [(5, 1), (1, 5), (-1, 2), (2, 0)])
def test_matrix_rejects_out_of_range(p, i):
    with pytest.raises(ValueError):
        matrix_level(p, i)


def test_level_mappings():
    assert MATRIX_TO_LEVEL3 == {"無": "低", "極低": "低", "低": "低", "中": "中", "高": "高", "極高": "高"}
    assert [IMPACT_TO_LEVEL3[i] for i in range(1, 5)] == ["低", "低", "中", "高"]
    assert [PROBABILITY_TO_LEVEL3[p] for p in range(0, 5)] == ["低", "低", "低", "中", "高"]


def test_reference_articles_reproduced():
    """COVID-19 (2020): import 高 x impact 高 -> 極高 -> 高.  SFTS (2023): 中 x 中 -> 中."""
    assert matrix_level(4, 4) == "極高" and MATRIX_TO_LEVEL3[matrix_level(4, 4)] == "高"
    assert MATRIX_TO_LEVEL3[matrix_level(3, 3)] == "中"


def test_example_audit(data):
    au = audit(Assessment.model_validate(data))
    assert au.overall_computed_level == "低"
    assert au.overall_matrix_level == "低"
    assert au.overall_agrees
    assert au.credibility_computed == "中"  # capped by tier-4 news source
    assert au.ihr_yes_count == 1 and not au.ihr_meets_threshold
    assert [c.passes_rules for c in au.claims] == [True] * 5
    items = {i.item_id: i for i in au.items}
    r1 = items["R1"]
    # ECDC Fig 2.2: Q2 否 => 極低; impact inherited from R4 (Fig 3: Q5 是, Q6 否 => 低)
    assert (r1.probability, r1.impact, r1.impact_inherited) == (1, 2, True)
    assert r1.ecdc_probability.path_text.endswith("⇒ 極低")
    assert r1.matrix_level == "低"
    # high-exposure stratum: Fig 2.2 Q2 是 → Q3 是 → Q4 否 => 中; matrix 中 x 低 => 中 (surfaced)
    st = r1.strata_computed[1]
    assert (st["probability"], st["computed_level"], st["matrix_level"]) == (3, "中", "中")
    assert any(i.code == "stratum_higher" for i in au.issues)
    # impact: ECDC-derived 低 vs article-style proposed 高 -> shown side by side
    r4 = items["R4"]
    assert r4.impact == 2 and r4.computed_level == "低" and r4.proposed_level == "高" and not r4.agrees
    assert any(i.code == "level_mismatch" and i.path == "risk_items[R4]" for i in au.issues)
    # HAIRS cross-check is derived but never enters the matrix
    assert au.hairs_probability.label == "中" and au.hairs_impact.label == "中"
    assert sum(1 for i in au.issues if i.severity == "error") == 0


def _drop_paths(data):
    for r in data["risk_items"]:
        r.pop("ecdc", None)
        r.pop("ecdc_impact", None)
        for st in r["strata"]:
            st.pop("ecdc", None)
            st.pop("ecdc_impact", None)


def test_stated_scores_used_when_no_ecdc_path(data):
    _drop_paths(data)
    au = audit(Assessment.model_validate(data))
    assert sum(1 for i in au.issues if i.code == "ecdc_path_missing") == 4
    r1 = next(i for i in au.items if i.item_id == "R1")
    assert r1.ecdc_probability is None and r1.probability == data["risk_items"][0]["probability"]


def test_overall_driven_by_highest_probability_item(data):
    _drop_paths(data)
    data["risk_items"][1]["probability"] = 4  # R2 community: High x High -> 極高
    data["risk_items"][3]["impact"] = 4
    au = audit(Assessment.model_validate(data))
    assert au.overall_probability_from == "R2"
    assert au.overall_matrix_level == "極高"
    assert au.overall_computed_level == "高"


def test_impact_change_propagates_to_inheriting_items(data):
    _drop_paths(data)
    data["risk_items"][3]["impact"] = 4
    data["risk_items"][0]["probability"] = 3
    au = audit(Assessment.model_validate(data))
    r1 = next(i for i in au.items if i.item_id == "R1")
    assert (r1.probability, r1.impact, r1.matrix_level) == (3, 4, "高")
    assert r1.computed_level == "中"  # item result = probability alone


def test_ecdc_derived_value_wins_and_mismatch_is_warned(data):
    data["risk_items"][0]["probability"] = 4  # stated High, but path says Q2 否 => 極低
    au = audit(Assessment.model_validate(data))
    r1 = next(i for i in au.items if i.item_id == "R1")
    assert r1.probability == 1 and r1.stated_probability == 4
    msg = next(i.message for i in au.issues if i.code == "ecdc_mismatch" and i.path == "risk_items[R1]")
    assert "4（高）" in msg and "1（極低）" in msg


def test_uncertain_answer_takes_higher_branch(data):
    r1 = data["risk_items"][0]
    r1["ecdc"]["answers"][0]["answer"] = "不確定"  # Q2 uncertain; Q3/Q4 unanswered
    au = audit(Assessment.model_validate(data))
    ia = next(i for i in au.items if i.item_id == "R1")
    assert ia.probability == 4  # precautionary: Q2 是 → Q3 是 → Q4 是 => 高
    assert ia.ecdc_probability.uncertain == ["Q2"] and ia.ecdc_probability.missing == ["Q3", "Q4"]
    codes = {i.code for i in au.issues}
    assert {"ecdc_precautionary", "ecdc_path_incomplete"} <= codes


def test_wrong_algorithm_for_item_kind_rejected(data):
    data["risk_items"][0]["ecdc"]["algorithm"] = "3"
    with pytest.raises(ValidationError, match="演算法須為"):
        Assessment.model_validate(data)


def test_question_not_in_algorithm_rejected(data):
    data["risk_items"][0]["ecdc"]["answers"].append({"q": "Q1", "answer": "是", "rationale": "x"})
    with pytest.raises(ValidationError, match="無此問題"):
        Assessment.model_validate(data)  # Q1 does not exist in Figure 2.2


def test_mismatch_is_surfaced_not_overwritten(data):
    data["risk_items"][0]["proposed_level"] = "高"
    data["risk_items"][3]["proposed_level"] = "低"
    data["overall"]["proposed_level"] = "中"
    a = apply_audit(Assessment.model_validate(data))
    assert a.risk_items[0].proposed_level == "高"  # untouched
    r1 = next(i for i in a.audit.items if i.item_id == "R1")
    assert r1.computed_level == "低" and not r1.agrees
    assert not a.audit.overall_agrees
    codes = {i.code for i in a.audit.issues}
    assert {"level_mismatch", "overall_mismatch"} <= codes


def test_confirmed_claim_needs_independent_source(data):
    # only the news itself as support -> rule fails, suggests 無法證實
    data["claims"][0]["evidence"] = [{"source_id": "S1", "stance": "支持", "quote_or_summary": "x"}]
    au = audit(Assessment.model_validate(data))
    c1 = au.claims[0]
    assert not c1.passes_rules and c1.suggested_verdict == "無法證實"
    assert any(i.code == "claim_rule" and i.severity == "error" for i in au.issues)


def test_same_publisher_is_not_independent(data):
    data["sources"][1]["publisher"] = data["sources"][0]["publisher"]  # S2 same publisher as news
    data["claims"][0]["evidence"] = [{"source_id": "S2", "stance": "支持", "quote_or_summary": "x"}]
    au = audit(Assessment.model_validate(data))
    assert not au.claims[0].passes_rules


def test_source_without_url_is_not_independent(data):
    data["sources"][1]["url"] = None
    data["sources"][1]["retrieval"] = "未取得"
    data["claims"][0]["evidence"] = [{"source_id": "S2", "stance": "支持", "quote_or_summary": "x"}]
    assert not audit(Assessment.model_validate(data)).claims[0].passes_rules


def test_contradiction_requires_official_source(data):
    data["claims"][0]["verdict"] = "與官方資訊不符"
    data["claims"][0]["evidence"] = [{"source_id": "S2", "stance": "反駁", "quote_or_summary": "x"}]
    assert audit(Assessment.model_validate(data)).claims[0].passes_rules
    data["sources"][1]["tier"] = 3
    assert not audit(Assessment.model_validate(data)).claims[0].passes_rules


def test_official_contradiction_makes_credibility_low(data):
    data["claims"][0]["verdict"] = "與官方資訊不符"
    data["claims"][0]["evidence"] = [{"source_id": "S2", "stance": "反駁", "quote_or_summary": "x"}]
    assert audit(Assessment.model_validate(data)).credibility_computed == "低"


def test_confidence_capped_single_publisher(data):
    r = data["risk_items"][1]  # R2 stated 高
    for b in r["evidence"]:
        b["source_ids"] = ["S2"]
    ia = next(i for i in audit(Assessment.model_validate(data)).items if i.item_id == "R2")
    assert ia.stated_confidence == "高" and ia.effective_confidence == "中"
    assert any("單一" in c for c in ia.confidence_caps)


def test_confidence_capped_low_tier_only(data):
    data["sources"].append({"id": "S99", "url": "https://example.com/a", "title": "t", "publisher": "Blog A",
                            "accessed_date": "2026-11-19", "tier": 4, "retrieval": "全文"})
    data["sources"].append({"id": "S98", "url": "https://example.org/b", "title": "t", "publisher": "Blog B",
                            "accessed_date": "2026-11-19", "tier": 3, "retrieval": "全文"})
    for b in data["risk_items"][1]["evidence"]:
        b["source_ids"] = ["S99", "S98"]
    ia = next(i for i in audit(Assessment.model_validate(data)).items if i.item_id == "R2")
    assert ia.effective_confidence == "低"


def test_confidence_capped_snippets_only(data):
    for b in data["risk_items"][1]["evidence"]:
        b["source_ids"] = ["S11", "S1"]  # ECDC snippet + news snippet
    ia = next(i for i in audit(Assessment.model_validate(data)).items if i.item_id == "R2")
    assert ia.effective_confidence == "中"
    assert any("搜尋摘要" in c for c in ia.confidence_caps)


def test_uncited_bullets_flagged_and_capped(data):
    for b in data["risk_items"][1]["evidence"]:
        b["source_ids"] = []
    au = audit(Assessment.model_validate(data))
    ia = next(i for i in au.items if i.item_id == "R2")
    assert ia.effective_confidence == "低" and ia.uncited_bullets == 4
    assert sum(1 for i in au.issues if i.code == "uncited") >= 4
    assert au.overall_confidence == "低"


def test_unknown_source_reference_is_error(data):
    data["risk_items"][0]["evidence"][0]["source_ids"] = ["S404"]
    au = audit(Assessment.model_validate(data))
    assert any(i.code == "unknown_source" and i.severity == "error" for i in au.issues)


def test_ihr_threshold(data):
    for q in data["ihr_annex2"]["questions"][:2]:
        q["answer"] = "是"
    au = audit(Assessment.model_validate(data))
    assert au.ihr_yes_count == 2 and au.ihr_meets_threshold
    data["ihr_annex2"]["questions"][1]["answer"] = "不確定"
    au = audit(Assessment.model_validate(data))
    assert not au.ihr_meets_threshold and "不確定" in au.ihr_note
    data["ihr_annex2"]["always_notifiable_disease"] = True
    assert audit(Assessment.model_validate(data)).ihr_meets_threshold


def test_decision_requires_recommended_option(data):
    for o in data["decision"]["options"]:
        o["recommended"] = False
    au = audit(Assessment.model_validate(data))
    assert any(i.code == "no_recommended_option" for i in au.issues)


def test_input_audit_is_ignored_and_recomputed(data):
    a = apply_audit(Assessment.model_validate(data))
    tampered = a.model_dump()
    tampered["audit"]["overall_computed_level"] = "高"
    again = apply_audit(Assessment.model_validate(tampered))
    assert again.audit.overall_computed_level == "低"


def test_reassessment_date_must_be_future(data):
    data["reassessment_date"] = "2026-11-01"
    assert any(i.code == "reassessment_past" for i in audit(Assessment.model_validate(data)).issues)


# ---------------------------------------------------------------------------
# Regression: the three Taiwan CDC 疫情報導 risk tables are reproduced.
# Article 3-level judgments are encoded on the 1-5 scales as 低=2, 中=3, 高=4.
# ---------------------------------------------------------------------------

L = {"低": 2, "中": 3, "高": 4}


def _prob_item(iid, name, level, strata=()):
    return {"id": iid, "name": name, "kind": "機率", "question": name + "？",
            "evidence": [{"text": "x", "source_ids": ["S2"]}],
            "level_definitions": {"低": "a", "中": "b", "高": "c"},
            "probability": L[level], "impact": None, "proposed_level": level,
            "strata": [{"name": n, "probability": L[lv], "proposed_level": lv} for n, lv in strata],
            "confidence": "中", "confidence_reason": "x"}


def _impact_item(iid, level, strata=()):
    return {"id": iid, "name": "衝擊", "kind": "衝擊", "question": "衝擊？",
            "evidence": [{"text": "x", "source_ids": ["S2"]}],
            "level_definitions": {"低": "a", "中": "b", "高": "c"},
            "probability": None, "impact": L[level], "proposed_level": level,
            "strata": [{"name": n, "impact": L[lv], "proposed_level": lv} for n, lv in strata],
            "confidence": "中", "confidence_reason": "x"}


def _run(data, items, overall):
    data["risk_items"] = items
    data["overall"]["proposed_level"] = overall
    au = audit(Assessment.model_validate(data))
    return au, {ia.item_id: ia for ia in au.items}


def test_article_covid19_2020(data):
    au, it = _run(data, [_prob_item("R1", "境外移入風險", "高"), _prob_item("R2", "國內社區流行風險", "中"),
                         _impact_item("R3", "高")], "高")
    assert [it[k].computed_level for k in ("R1", "R2", "R3")] == ["高", "中", "高"]
    assert all(ia.agrees for ia in au.items)
    assert au.overall_computed_level == "高" and au.overall_agrees


def test_article_sfts_2023(data):
    au, it = _run(data, [_prob_item("R1", "境外移入風險（人類病例）", "低"), _prob_item("R2", "境外移入風險（感染動物）", "中"),
                         _prob_item("R3", "國內社區流行風險", "低"), _prob_item("R4", "國內野外感染風險", "中"),
                         _impact_item("R5", "中")], "中")
    assert [it[k].computed_level for k in ("R1", "R2", "R3", "R4", "R5")] == ["低", "中", "低", "中", "中"]
    assert all(ia.agrees for ia in au.items)
    assert au.overall_computed_level == "中" and au.overall_agrees


def test_article_zika_2016_items_and_strata(data):
    au, it = _run(data, [
        _prob_item("R1", "境外移入風險", "高"),
        _prob_item("R2", "社區流行風險", "中", strata=[("登革熱非流行季", "低"), ("南高屏地區登革熱流行季期間", "中"),
                                                    ("中北部登革熱流行季期間", "低")]),
        _impact_item("R3", "高", strata=[("孕婦、胎兒及新生兒", "高"), ("孩童及一般民眾", "低")]),
    ], "高")
    assert it["R1"].computed_level == "高"
    assert [s["computed_level"] for s in it["R2"].strata_computed] == ["低", "中", "低"]
    assert [s["computed_level"] for s in it["R3"].strata_computed] == ["高", "低"]
    assert all(ia.agrees for ia in au.items)
    assert not any(i.code == "stratum_mismatch" for i in au.issues)
