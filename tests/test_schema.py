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
