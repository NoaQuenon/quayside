from ipaddress import IPv4Address, IPv4Network

import pytest

from quayside.render import build_plan
from quayside.spec import Scenario, load_scenario


@pytest.fixture
def smoke(scenarios_dir):
    return build_plan(load_scenario(scenarios_dir / "smoke.yaml"))


def test_addressing_is_deterministic(smoke):
    addr = smoke.addressing

    # Everything is allocated in the same order: cloud, then edge, then factory
    assert addr.site_subnets == {
        "cloud": IPv4Network("10.77.0.0/24"),
        "edge": IPv4Network("10.77.1.0/24"),
        "factory": IPv4Network("10.77.2.0/24"),
    }

    assert addr.gateway_ips["edge"] == IPv4Address("10.77.1.2")
    assert addr.link_subnets["edge-cloud"] == IPv4Network("10.77.255.0/29")
    assert addr.component_ips["probe-factory"] == IPv4Address("10.77.2.10")

    assert addr.link_ips["edge-cloud"] == {
        "edge": IPv4Address("10.77.255.2"),
        "cloud": IPv4Address("10.77.255.3"),
    }


def test_explicit_addresses_are_respected():
    scn = Scenario.model_validate(
        {
            "name": "t",
            "sites": {"a": {"subnet": "10.77.0.0/24"}, "b": {}},
            "links": {"ab": {"a": "a", "b": "b"}},
            "components": {
                "x": {"image": "i", "site": "a", "ip": "10.77.0.10"},
                "w": {"image": "i", "site": "a"},
            },
        }
    )

    addr = build_plan(scn).addressing

    assert addr.site_subnets["b"] == IPv4Network("10.77.1.0/24")
    assert addr.component_ips["x"] == IPv4Address("10.77.0.10")
    assert addr.component_ips["w"] == IPv4Address("10.77.0.11")


def test_routes_follow_the_chain(smoke):
    factory = {str(r.destination): (str(r.via), r.link) for r in smoke.routes["factory"]}
    edge_on_fe = str(smoke.addressing.link_ips["factory-edge"]["edge"])

    assert factory == {
        "10.77.0.0/24": (edge_on_fe, "factory-edge"),
        "10.77.1.0/24": (edge_on_fe, "factory-edge"),
    }


def test_routes_prefer_low_latency():
    scn = Scenario.model_validate(
        {
            "name": "t",
            "sites": {"a": {}, "b": {}, "c": {}},
            "links": {
                "ab": {"a": "a", "b": "b", "latency": 1},
                "bc": {"a": "b", "b": "c", "latency": 1},
                "ac": {"a": "a", "b": "c", "latency": 50},
            },
        }
    )

    plan = build_plan(scn)
    to_c = next(r for r in plan.routes["a"] if r.destination == plan.addressing.site_subnets["c"])

    assert to_c.link == "ab"
