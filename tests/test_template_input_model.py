import pytest

from src.template_input_model import (
    decode_bytes,
    encode_params,
    load_template,
    validate_ranges,
    roundtrip_close,
    template_path_for_block,
)

# The filter_3p3z template targets the deprecated 3p3z reference firmware that
# was used early in the project. Its YAML layout (input_models/templates/) is
# not shipped in this archive, so skip rather than fabricate a byte layout.
pytestmark = pytest.mark.skipif(
    not template_path_for_block("filter_3p3z").exists(),
    reason="input_models/templates/filter_3p3z.yaml not present (deprecated 3p3z reference firmware)",
)


def test_load_template_filter_3p3z():
    t = load_template("filter_3p3z")
    assert t.name == "filter_3p3z"
    assert t.record_size_bytes == 48
    assert t.endianness == "little"
    assert len(t.fields) > 0


def test_q23_roundtrip_close():
    t = load_template("filter_3p3z")
    p0 = {
        "cx_q23[0]": 0.5,
        "cx_q23[1]": -0.5,
        "cx_q23[2]": 0.0,
        "cx_q23[3]": 0.9,
        "cy_q23[0]": 0.25,
        "cy_q23[1]": -0.25,
        "cy_q23[2]": 0.0,
        "scaleCx": 7,
        "scaleCy": 0,
        "gIn": 3,
        "gOut": 7,
        "out_offset": 0,
        "limit_max": 123,
        "limit_min": -123,
        "input_sample": 456,
    }

    b = encode_params(p0, t)
    assert len(b) == 48

    p1 = decode_bytes(b, t)
    assert p1 is not None
    assert validate_ranges(p1, t)
    assert roundtrip_close(p0, p1, t, q_tol_lsb=1)
