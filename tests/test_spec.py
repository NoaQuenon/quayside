import pytest

from quayside.spec.units import parse_ms


@pytest.mark.parametrize(
    ("raw", "ms"), [("5ms", 5.0), ("1.5s", 1500.0), ("200us", 0.2), (3, 3.0), ("7", 7.0)]
)
def test_parse_ms(raw: str | int, ms: float) -> None:
    assert parse_ms(raw) == pytest.approx(ms)


@pytest.mark.parametrize("raw", ["5 min", "-1ms", "superhyperfast", True])
def test_parse_ms_rejects(raw: str | bool) -> None:
    with pytest.raises(ValueError):
        parse_ms(raw)
