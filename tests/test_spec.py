import pytest

from quayside.spec.units import parse_ms


@pytest.mark.parametrize(
    ("raw", "ms"), [("5ms", 5), ("1.5s", 1500), ("200us", 0.2), ("7", 7)]
)
def test_parse_ms(raw, ms):
    assert parse_ms(raw) == pytest.approx(ms)


@pytest.mark.parametrize("raw", ["5 min", "-1ms", "superfast", True])
def test_parse_ms_rejects(raw):
    with pytest.raises(ValueError):
        parse_ms(raw)
