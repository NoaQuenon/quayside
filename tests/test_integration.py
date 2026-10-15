import re
import shutil

import pytest

from quayside.runtime import Testbed
from quayside.spec import load_scenario

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("docker") is None, reason="docker missing"),
]


def avg_rtt(testbed: Testbed, src: str, dst: str) -> float:
    container = testbed.containers()[src]
    code, out = container.exec_run(["ping", "-c", "10", "-i", "0.2", "-q", dst])

    assert code == 0, out.decode()
    match = re.search(r"= [\d.]+/([\d.]+)/", out.decode())  # Match the RTT line in ping output
    assert match, out.decode()

    return float(match.group(1))


@pytest.fixture(scope="module")
def smoke(tmp_path_factory, request):
    scenarios = request.config.rootpath / "scenarios"

    scn = load_scenario(
        scenarios / "smoke.yaml", ["links.factory-edge.jitter=0", "links.edge-cloud.jitter=0"]
    )

    base = tmp_path_factory.mktemp("smoke")
    testbed = Testbed(scn, base / "work")

    testbed.up()
    yield testbed  # So we block here
    testbed.down()


def test_rtt_matches_link_latency(smoke):
    # 2 * 5 = 10ms
    assert 10 <= avg_rtt(smoke, "probe-factory", "probe-edge") < 15

    # 2 * (5 + 20) = 50ms
    assert 50 <= avg_rtt(smoke, "probe-factory", "probe-cloud") < 65


def test_testbed_has_no_internet(smoke):
    probe = smoke.containers()["probe-factory"]
    code, _ = probe.exec_run(["ping", "-c", "1", "-W", "2", "8.8.8.8"])  # Ping Google

    assert code != 0  # Ping should fail


def test_set_link_at_runtime(smoke):
    smoke.set_link("factory-edge", latency="30ms")

    try:
        # 2 * 30 = 60ms
        assert 60 <= avg_rtt(smoke, "probe-factory", "probe-edge") < 65

    finally:
        smoke.set_link("factory-edge", latency="5ms")
