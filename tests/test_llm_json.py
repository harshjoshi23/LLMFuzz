import pytest

from src.utils.llm_json import (
    LLMOutputParseError,
    parse_json_array,
    parse_json_object,
    validate_constraint_items,
    validate_seed_suggestions,
)


def test_parse_json_array_direct():
    arr = parse_json_array('[{"a": 1}]')
    assert arr == [{"a": 1}]


def test_parse_json_array_code_fence():
    arr = parse_json_array('```json\n[{"a": 1}]\n```')
    assert arr == [{"a": 1}]


def test_parse_json_array_embedded():
    arr = parse_json_array('hello\n[{"a": 1}, {"b": 2}]\nthanks')
    assert arr == [{"a": 1}, {"b": 2}]


def test_parse_json_array_missing():
    with pytest.raises(LLMOutputParseError):
        parse_json_array('no json here')


def test_validate_constraint_items():
    ok, _ = validate_constraint_items([{"name": "X"}])
    assert ok
    ok, _ = validate_constraint_items([{"bad": 1}])
    assert not ok



def test_validate_seed_suggestions():
    ok, _ = validate_seed_suggestions([
        {"parameter": "address", "value": 32, "category": "boundary", "reasoning": "test"}
    ])
    assert ok
    ok, _ = validate_seed_suggestions([{"parameter": "x"}])
    assert not ok


def test_parse_json_object_direct():
    obj = parse_json_object('{"a": 1}')
    assert obj == {"a": 1}
