import asyncio
import hashlib
import logging
import os
import random
import signal
import socket
import struct
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from ipaddress import IPv4Address
from pathlib import Path

from pydantic import BaseModel

log = logging.getLogger(__name__)

ROUTE_WAIT_TIMEOUT_S = 120.0


@dataclass(frozen=True)
class ComponentContext:
    name: str
    site: str
    seed: int
    data_dir: Path
    gateway: IPv4Address | None
    layer: str = ""

    @classmethod
    def from_env(cls) -> ComponentContext:
        # Infos are provided by Docker env
        gateway = os.environ.get("QS_GATEWAY")

        return cls(
            name=os.environ.get("QS_COMPONENT", socket.gethostname()),
            site=os.environ.get("QS_SITE", ""),
            seed=int(os.environ.get("QS_SEED", "0")),
            data_dir=Path(os.environ.get("QS_DATA", "/data")),
            gateway=IPv4Address(gateway) if gateway else None,
            layer=os.environ.get("QS_LAYER", ""),
        )

    def rng(self, stream: str) -> random.Random:
        digest = hashlib.sha256(f"{self.seed}/{self.name}/{stream}".encode()).digest()
        return random.Random(int.from_bytes(digest[:8], "big"))


def configure_logging(name: str) -> None:
    logging.basicConfig(
        level=os.environ.get("QS_LOG_LEVEL", "INFO"),
        format=f"%(asctime)s {name} %(levelname)s %(name)s: %(message)s",
    )


def default_gateway() -> IPv4Address | None:
    """Returns the current IPv4 default gateway read from `/proc`"""

    try:
        lines = Path("/proc/net/route").read_text().splitlines()[1:]

    except OSError:
        return None

    for line in lines:
        fields = line.split()

        if len(fields) > 2 and fields[1] == "00000000":
            address = struct.pack("<I", int(fields[2], 16))
            return IPv4Address(address)

    return None


async def wait_for_gateway(gateway: IPv4Address) -> None:
    """Blocks until the orchestrator has configured the site gateway as the default route"""

    try:
        async with asyncio.timeout(ROUTE_WAIT_TIMEOUT_S):
            while default_gateway() != gateway:  # noqa: ASYNC110 - we can't really wait for an event here, don't know if there's a better solution...
                await asyncio.sleep(0.2)

    except TimeoutError:
        raise TimeoutError(f"default route never pointed at site gateway {gateway}") from None

    log.info("network ready (default route via %s)", gateway)


ComponentMain = Callable[[ComponentContext, BaseModel], Awaitable[None]]


async def _supervise(ctx: ComponentContext, main: ComponentMain, config: BaseModel) -> None:
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    assert task is not None

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)

    if ctx.gateway is not None:
        await wait_for_gateway(ctx.gateway)

    try:
        await main(ctx, config)

    except asyncio.CancelledError:
        log.info("stopping")


def run_component(main: ComponentMain, config: BaseModel, ctx: ComponentContext | None = None) -> None:
    ctx = ctx or ComponentContext.from_env()
    configure_logging()
    ctx.data_dir.mkdir(parents=True, exist_ok=True)

    asyncio.run(_supervise(ctx, main, config))


def split_endpoint(endpoint: str, default_port: int) -> tuple[str, int]:
    host, sep, port = endpoint.rpartition(":")

    if not sep:
        return endpoint, default_port

    if not host or not port.isdigit():
        raise ValueError(f"invalid endpoint {endpoint}, expected 'host' or 'host:port'")

    return host, int(port)


async def sleep_until(deadline: float) -> None:
    delay = deadline - time.monotonic()

    if delay > 0:
        await asyncio.sleep(delay)
