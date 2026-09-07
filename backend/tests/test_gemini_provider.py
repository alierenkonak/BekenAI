from __future__ import annotations

from typing import Any

from app.llm.gemini import _gemini_json_schema
from app.llm.models import GroundedAnswer, SupportReport


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        result = set(value)
        for child in value.values():
            result.update(_keys(child))
        return result
    if isinstance(value, list):
        result: set[str] = set()
        for child in value:
            result.update(_keys(child))
        return result
    return set()


def test_gemini_schema_inlines_refs_and_drops_unsupported_constraints() -> None:
    for model in (GroundedAnswer, SupportReport):
        schema = _gemini_json_schema(model)
        keys = _keys(schema)
        assert "$defs" not in keys
        assert "$ref" not in keys
        assert "default" not in keys
        assert "pattern" not in keys
        assert "minLength" not in keys
        assert "maxLength" not in keys
        assert "minItems" not in keys
        assert "maxItems" not in keys
        assert "title" not in keys
        assert schema["type"] == "object"


def test_gemini_schema_compacts_nullable_objects_without_any_of() -> None:
    schema = _gemini_json_schema(GroundedAnswer)
    primary = schema["properties"]["primary_answer"]
    doctrine = schema["properties"]["doctrine_answer"]
    assert primary["type"] == ["object", "null"]
    assert doctrine["type"] == ["object", "null"]
    assert "anyOf" not in primary
    assert "anyOf" not in doctrine
