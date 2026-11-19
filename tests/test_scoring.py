import pytest

from epi_risk_agent.schema import Assessment
from epi_risk_agent.scoring import (
    IMPACT_TO_LEVEL3,
    MATRIX_TO_LEVEL3,
    RISK_MATRIX,
    apply_audit,
    audit,
    matrix_level,
)


def band(p, i):
    s = p * i
    return "低" if s <= 4 else "中" if s <= 9 else "高" if s <= 15 else "極高"


@pytest.mark.parametrize("p", range(1, 6))
@pytest.mark.parametrize("i", range(1, 6))
def test_matrix_table_matches_documented_banding(p, i):
    assert RISK_MATRIX[p][i] == band(p, i)
    assert RISK_MATRIX[p][i] == RISK_MATRIX[i][p]  # symmetric


def test_matrix_monotonic():
    order = {"低": 0, "中": 1, "高": 2, "極高": 3}
    for p in range(1, 6):
        for i in range(1, 5):
            assert order[RISK_MATRIX[p][i]] <= order[RISK_MATRIX[p][i + 1]]
            assert order[RISK_MATRIX[i][p]] <= order[RISK_MATRIX[i + 1][p]]


def test_matrix_rejects_out_of_range():
    with pytest.raises(ValueError):
        matrix_level(0, 3)


def test_level_mappings():
    assert MATRIX_TO_LEVEL3 == {"低": "低", "中": "中", "高": "高", "極高": "高"}
    assert [IMPACT_TO_LEVEL3[i] for i in range(1, 6)] == ["低", "低", "中", "高", "高"]


def test_reference_articles_reproduced():
    """The 3-level results of the reference articles are reproducible.

    COVID-19 (2020): import 高 x impact 高 -> 高.  SFTS (2023): 中 x 中 -> 中.
    """
    assert MATRIX_TO_LEVEL3[matrix_level(4, 4)] == "高"
    assert MATRIX_TO_LEVEL3[matrix_level(3, 3)] == "中"
    assert MATRIX_TO_LEVEL3[matrix_level(1, 4)] == "低"


def test_example_audit(data):
    au = audit(Assessment.model_validate(data))
    assert au.overall_computed_level == "低"
    assert au.overall_matrix_level == "低"
    assert au.overall_agrees
    assert au.credibility_computed == "中"  # capped by tier-4 news source
    assert au.ihr_yes_count == 1 and not au.ihr_meets_threshold
    assert [c.passes_rules for c in au.claims] == [True] * 5
    r1 = next(i for i in au.items if i.item_id == "R1")
    assert r1.impact_inherited and r1.impact == 4
    # high-exposure stratum: probability 2 -> 低, but matrix risk 2x4 -> 中 (surfaced, not hidden)
    assert r1.strata_computed[1]["computed_level"] == "低"
    assert r1.strata_computed[1]["matrix_level"] == "中" and r1.strata_computed[1]["matrix_level3"] == "中"
    assert any(i.code == "stratum_higher" for i in au.issues)
    assert sum(1 for i in au.issues if i.severity == "error") == 0


def test_overall_driven_by_highest_probability_item(data):
    data["risk_items"][1]["probability"] = 4  # R2 community 4 x 4 -> 極高
    au = audit(Assessment.model_validate(data))
    assert au.overall_probability_from == "R2"
    assert au.overall_matrix_level == "極高"
    assert au.overall_computed_level == "高"


def test_impact_change_propagates_to_inheriting_items(data):
    data["risk_items"][3]["impact"] = 5
    data["risk_items"][0]["probability"] = 3
    au = audit(Assessment.model_validate(data))
    r1 = next(i for i in au.items if i.item_id == "R1")
    assert (r1.probability, r1.impact, r1.matrix_level) == (3, 5, "高")
    assert r1.computed_level == "中"  # item result = probability alone


def test_mismatch_is_surfaced_not_overwritten(data):
    data["risk_items"][0]["proposed_level"] = "高"
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
