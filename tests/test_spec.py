import pytest
from pydantic import ValidationError

from quayside.spec.models import Scenario
from quayside.spec.units import parse_ms


def minimal(**extra):
    data = {
        "name": "t",
        "sites": {"a": {}, "b": {}},
        "links": {"ab": {"a": "a", "b": "b"}},
        "components": {"c": {"image": "x", "site": "a"}},
    }

    return merge(data, extra)


def merge(base: dict, patch: dict) -> dict:
    merged = dict(base)

    for key, value in patch.items():
        if value is None:
            merged.pop(key, None)

        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge(merged[key], value)

        else:
            merged[key] = value

    return merged


@pytest.mark.parametrize(
    ("raw", "ms"), [("5ms", 5), ("1.5s", 1500), ("200us", 0.2), ("7", 7)]
)
def test_parse_ms(raw, ms):
    assert parse_ms(raw) == pytest.approx(ms)


@pytest.mark.parametrize("raw", ["5 min", "-1ms", "superfast", True])
def test_parse_ms_rejects(raw):
    with pytest.raises(ValueError):
        parse_ms(raw)


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"links": {"ab": {"b": "zz"}}}, "unknown site"),
        ({"links": {"ab": None}}, "not all connected"),
        ({"links": {"ba": {"a": "b", "b": "a"}}}, "connect the same sites"),
        ({"components": {"c": {"host": "h"}}}, "exactly one of"),
        ({"components": {"c": {"site": None, "host": "h"}}}, "unknown host"),
        ({"components": {"gw-a": {"image": "x", "site": "a"}}}, "reserved"),
        ({"components": {"Bad_Name": {"image": "x", "site": "a"}}}, "must match"),
        ({"links": {"ab": {"loss": 150}}}, "less than or equal"),
        ({"links": {"ab": {"rate": "fast"}}}, "invalid rate"),
        ({"sites": {"a": {"colour": "red"}}}, "Extra inputs"),
        ({"components": {"c": {"image": None}}}, "Field required"),
    ],
)
def test_invalid_scenarios(patch, message):
    with pytest.raises(ValidationError, match=message):
        Scenario.model_validate(minimal(**patch))
