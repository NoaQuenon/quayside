import pytest
from pydantic import ValidationError

from quayside.spec import Scenario, load_scenario
from quayside.spec.loader import apply_override, deep_merge
from quayside.spec.units import parse_ms


def minimal(**extra):
    data = {
        "name": "t",
        "sites": {"a": {}, "b": {}},
        "links": {"ab": {"a": "a", "b": "b"}},
        "components": {"c": {"image": "x", "site": "a"}},
    }

    return deep_merge(data, extra)


@pytest.mark.parametrize(("raw", "ms"), [("5ms", 5), ("1.5s", 1500), ("200us", 0.2), ("7", 7)])
def test_parse_ms(raw, ms):
    assert parse_ms(raw) == pytest.approx(ms)


@pytest.mark.parametrize("raw", ["5 min", "-1ms", "superfast", True])
def test_parse_ms_rejects(raw):
    with pytest.raises(ValueError):
        parse_ms(raw)


def test_deep_merge_null_deletes():
    assert deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"c": None, "d": 3}}) == {"a": {"b": 1, "d": 3}}


def test_override_parses_yaml():
    data = apply_override({"links": {"x": {"latency": 1}}}, "links.x.latency=20ms")

    assert data == {"links": {"x": {"latency": "20ms"}}}
    assert apply_override({}, "a.b=[1, 2]") == {"a": {"b": [1, 2]}}


def test_smoke_loads(scenarios_dir):
    scn = load_scenario(scenarios_dir / "smoke.yaml")

    assert set(scn.sites) == {"factory", "edge", "cloud"}
    assert scn.links["edge-cloud"].rate == "100mbit"
    assert scn.site_of("probe-edge") == "edge"


def test_extends_attribute_overrides(scenarios_dir):
    scn = load_scenario(scenarios_dir / "smoke-degraded.yaml", ["links.factory-edge.latency=1s"])

    assert scn.name == "smoke-degraded"
    assert scn.links["edge-cloud"].latency == 80
    assert scn.links["edge-cloud"].a == "edge"  # From the base smoke.yaml
    assert scn.links["factory-edge"].latency == 1000


def test_circular_extends(tmp_path):
    (tmp_path / "a.yaml").write_text("extends: b.yaml\n")
    (tmp_path / "b.yaml").write_text("extends: a.yaml\n")

    with pytest.raises(ValueError, match="circular"):
        load_scenario(tmp_path / "a.yaml")


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
