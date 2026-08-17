from __future__ import annotations


def _make_truncated_json_array() -> str:
    # Two items, then cut mid-string
    s = '[{"name":"A","min":0,"max":1,"valid_values":null,"type":"range","unit":"V","confidence":0.9},'
    s += '{"name":"B","min":2,"max":3,"valid_values":null,"type":"range","unit":"'
    return s  # truncated


def test_salvage_truncated_json_array_returns_non_empty():
    from src.utils.llm_json import parse_json_array

    items = parse_json_array(_make_truncated_json_array())
    assert isinstance(items, list)
    assert len(items) >= 1


def test_cap_to_30_items():
    from src.utils.llm_json import parse_json_array

    items = [{"name": f"c{i}", "min": i, "max": i + 1, "valid_values": None, "type": "range", "unit": "V", "confidence": 0.5} for i in range(50)]
    s = __import__("json").dumps(items)
    parsed = parse_json_array(s)
    assert len(parsed) == 50
    assert len(parsed[:30]) == 30
