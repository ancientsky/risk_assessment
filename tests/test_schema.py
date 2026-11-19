import pytest
from pydantic import ValidationError

from epi_risk_agent.schema import Assessment, llm_output_schema


def test_example_validates(data):
    a = Assessment.model_validate(data)
    assert a.event.news_source_id == "S1"
    assert {r.kind for r in a.risk_items} == {"機率", "衝擊"}


def test_requires_impact_item(data):
    data["risk_items"] = [r for r in data["risk_items"] if r["kind"] != "衝擊"]
    with pytest.raises(ValidationError, match="衝擊"):
        Assessment.model_validate(data)


def test_probability_item_needs_probability(data):
    data["risk_items"][0]["probability"] = None
    with pytest.raises(ValidationError, match="probability"):
        Assessment.model_validate(data)


def test_scores_bounded(data):
    data["risk_items"][0]["probability"] = 6
    with pytest.raises(ValidationError):
        Assessment.model_validate(data)


def test_duplicate_ids_rejected(data):
    data["claims"][1]["id"] = data["claims"][0]["id"]
    with pytest.raises(ValidationError, match="重複"):
        Assessment.model_validate(data)


def test_ihr_needs_four_distinct_questions(data):
    data["ihr_annex2"]["questions"] = data["ihr_annex2"]["questions"][:3]
    with pytest.raises(ValidationError):
        Assessment.model_validate(data)


def test_url_scheme_enforced(data):
    data["sources"][1]["url"] = "javascript:alert(1)"
    with pytest.raises(ValidationError):
        Assessment.model_validate(data)


def test_unknown_fields_forbidden(data):
    data["event"]["surprise"] = 1
    with pytest.raises(ValidationError):
        Assessment.model_validate(data)


def test_enum_values_are_zh_tw(data):
    data["claims"][0]["verdict"] = "confirmed"
    with pytest.raises(ValidationError):
        Assessment.model_validate(data)


def test_llm_schema_excludes_audit():
    s = llm_output_schema()
    assert "audit" not in s["properties"]
    assert "risk_items" in s["properties"]


@pytest.mark.parametrize("field,value,ok", [("probability", 0, True), ("probability", 4, True), ("probability", 5, False),
                                            ("impact", 4, True), ("impact", 5, False), ("impact", 0, False)])
def test_ecdc_scale_bounds(data, field, value, ok):
    item = data["risk_items"][0] if field == "probability" else data["risk_items"][3]
    item[field] = value
    if ok:
        Assessment.model_validate(data)
    else:
        with pytest.raises(ValidationError):
            Assessment.model_validate(data)


def test_hairs_question_ids_validated(data):
    data["hairs"]["impact"].append({"q": "Q13", "answer": "是", "rationale": "x"})
    with pytest.raises(ValidationError, match="無此問題"):
        Assessment.model_validate(data)


def test_legacy_hairs_questions_rejected(data):
    data["risk_items"][3]["hairs_questions"] = []
    with pytest.raises(ValidationError):
        Assessment.model_validate(data)
