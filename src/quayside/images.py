from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKER_DIR = REPO_ROOT / "docker"
IMAGE_TAG = "0.1"


@dataclass
class LocalImage:
    tag: str
    dockerfile: Path
    context: Path


GATEWAY = LocalImage(
    f"quayside/gateway:{IMAGE_TAG}", DOCKER_DIR / "gateway" / "Dockerfile", DOCKER_DIR / "gateway"
)

NETCTL = LocalImage(
    f"quayside/netctl:{IMAGE_TAG}", DOCKER_DIR / "netctl" / "Dockerfile", DOCKER_DIR / "netctl"
)
