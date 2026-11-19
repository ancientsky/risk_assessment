"""WHO 2012 Figure 3a matrix and the integrated synthesis (綜合評估)."""

import copy

import pytest

from epi_risk_agent.schema import Assessment
from epi_risk_agent.scoring import WHO_ACTIONS, WHO_MATRIX, WHO_TO_LEVEL3, audit, who_level

# WHO (2012) Figure 3a as published (colours per Table 6: green Low, yellow
# Moderate, orange High, red Very high). Rows = likelihood, columns =
# consequences Minimal, Minor, Moderate, Major, Severe.
G, Y, O, R = "低", "中", "高", "極高"
FIG3A = {
    5: [G, Y, O, R, R],  # Almost certain
    4: [G, Y, O, R, R],  # Highly likely
    3: [G, Y, O, O, R],  # Likely
    2: [G, G, Y, O, O],  # Unlikely
    1: [G, G, Y, O, O],  # Very unlikely
}


@pytest.mark.parametrize("lk", range(1, 6))
@pytest.mark.parametrize("cq", range(1, 6))
def test_who_matrix_equals_figure_3a(lk, cq):
    assert WHO_MATRIX[lk][cq] == FIG3A[lk][cq - 1]
    assert who_level(lk, cq) == FIG3A[lk][cq - 1]


def test_who_matrix_shape_and_mapping():
    assert sorted(WHO_MATRIX) == [1, 2, 3, 4, 5]
    assert all(sorted(row) == [1, 2, 3, 4, 5] for row in WHO_MATRIX.values())
    assert WHO_TO_LEVEL3 == {"低": "低", "中": "中", "高": "高", "極高": "高"}
    assert set(WHO_ACTIONS) == {"低", "中", "高", "極高"}
    with pytest.raises(ValueError):
        who_level(0, 3)


def _syn(data):
    return audit(Assessment.model_validate(data))


def _who(data, lk, cq, groups=()):
    data["who_rra"] = {"risk_question": "q", "likelihood": lk, "likelihood_rationale": "x", "consequences": cq,
                       "consequences_rationale": "x", "source_ids": ["S2"],
                       "groups": [{"name": n, "likelihood": a, "consequences": b, "rationale": "x"} for n, a, b in groups]}


def test_mers_example_synthesis(data):
    au = _syn(data)
    sy = au.synthesis
    assert sy.integrated_level == "低"  # ECDC is primary
    assert sy.consistency == "部分一致"  # WHO 中 vs ECDC 低 / article 低
    assert sy.cautious_cap == "中"
    assert sy.differences == ["WHO 2012：中（高於綜合等級 低）"]
    assert any(c.startswith("HAIRS 機率") for c in sy.cautions)
    assert sy.compact == "ECDC 低｜WHO 中｜HAIRS 機率中・衝擊中｜文章式判斷 低｜審慎上限 中"
    hairs_row = next(r for r in sy.rows if r.framework.startswith("UKHSA HAIRS"))
    assert hairs_row.level3 is None and "無合併等級" in hairs_row.native
    assert au.who.level == "中" and au.who.action == WHO_ACTIONS["中"]
    assert not any(i.code == "synthesis_note_missing" for i in au.issues)


def test_agree_without_who_and_hairs(data):
    data.pop("who_rra")
    data.pop("hairs")
    for r in data["risk_items"]:  # remove the high-exposure stratum so nothing exceeds the overall level
        r["strata"] = [s for s in r["strata"] if not s["name"].startswith("赴中東")]
    data["overall"]["synthesis_note"] = None
    au = _syn(data)
    sy = au.synthesis
    assert [r.framework for r in sy.rows] == ["ECDC 2019（主要）", "疫情報導式判斷"]
    assert (sy.consistency, sy.cautious_cap, sy.cautions, sy.note_required) == ("一致", "低", [], False)
    assert sy.compact == "ECDC 低｜文章式判斷 低｜審慎上限 低"
    assert any(i.code == "who_missing" for i in au.issues)
    assert not any(i.code == "synthesis_note_missing" for i in au.issues)


def test_partial_and_note_required(data):
    _who(data, 1, 3)  # Very unlikely x Moderate = 中
    data["overall"]["synthesis_note"] = None
    au = _syn(data)
    assert au.synthesis.consistency == "部分一致"
    assert any(i.code == "synthesis_note_missing" and i.severity == "warning" for i in au.issues)


def test_disagree_two_levels_apart(data):
    _who(data, 3, 4)  # Likely x Major = 高 vs ECDC 低
    au = _syn(data)
    sy = au.synthesis
    assert sy.consistency == "不一致" and sy.cautious_cap == "高"
    assert "WHO 2012：高（高於綜合等級 低）" in sy.differences


def test_article_judgment_counts_and_direction(data):
    _who(data, 1, 1)  # 低
    data["overall"]["proposed_level"] = "中"
    sy = _syn(data).synthesis
    assert sy.integrated_level == "低"  # article judgment never overrides ECDC
    assert sy.cautious_cap == "中" and sy.consistency == "部分一致"
    assert any(d.startswith("疫情報導式判斷：中") for d in sy.differences)


def test_groups_raise_cap_but_not_consistency(data):
    _who(data, 1, 1, groups=[("孕婦", 2, 5)])  # group Unlikely x Severe = 高
    data.pop("hairs")
    for r in data["risk_items"]:
        r["strata"] = [s for s in r["strata"] if not s["name"].startswith("赴中東")]
    sy = _syn(data).synthesis
    assert sy.consistency == "一致"
    assert sy.cautious_cap == "高"  # risk groups count toward the cap
    assert sy.cautions == ["WHO 2012／孕婦：高（高風險）"]
    assert sy.note_required


def test_hairs_component_higher_is_caution_only(data):
    data.pop("who_rra")
    for r in data["risk_items"]:
        r["strata"] = [s for s in r["strata"] if not s["name"].startswith("赴中東")]
    sy = _syn(data).synthesis
    assert sy.cautious_cap == "低"  # HAIRS excluded from the cap
    assert {c.split("：")[0] for c in sy.cautions} == {"HAIRS 機率", "HAIRS 衝擊"}


def test_who_group_names_unique(data):
    from pydantic import ValidationError

    d = copy.deepcopy(data)
    _who(d, 1, 1, groups=[("A", 1, 1), ("A", 2, 2)])
    with pytest.raises(ValidationError, match="重複"):
        Assessment.model_validate(d)


def test_who_source_ids_checked(data):
    data["who_rra"]["source_ids"] = ["S404"]
    au = _syn(data)
    assert any(i.code == "unknown_source" and i.path == "who_rra" for i in au.issues)
