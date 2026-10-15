import json
import subprocess
import time
from pathlib import Path
from typing import Any

import docker
import yaml
from docker import DockerClient
from docker.models.containers import Container

from quayside.images import GATEWAY, NETCTL, LocalImage
from quayside.render.compose import LABEL_ROLE, LABEL_SITE, render_compose
from quayside.render.plan import build_plan
from quayside.runtime.network import Network
from quayside.spec.models import LinkSpec, Scenario

DEFAULT_WORKDIR = Path(".quayside")


class Testbed:
    def __init__(self, scenario: Scenario, workdir: Path = DEFAULT_WORKDIR):
        self.dir = workdir / scenario.name
        self._docker: DockerClient | None = None
        self.plan = build_plan(scenario)

    @property
    def scenario(self) -> Scenario:
        return self.plan.scenario

    @property
    def compose_file(self) -> Path:
        return self.dir / "compose.yaml"

    @property
    def client(self) -> DockerClient:
        if self._docker is None:
            self._docker = docker.from_env()

        return self._docker

    def images(self) -> list[LocalImage]:
        return [GATEWAY, NETCTL]

    def build_images(self) -> None:
        """Builds all local images"""

        for image in self.images():
            cmd = [
                "docker",
                "build",
                "--quiet",
                "--tag",
                image.tag,
                "--file",
                str(image.dockerfile),
                str(image.context),
            ]

            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)

    def render(self) -> Path:
        """Writes the Docker Compose project and plan to the work directory"""

        self.dir.mkdir(parents=True, exist_ok=True)
        compose = render_compose(self.plan)
        self.compose_file.write_text(yaml.safe_dump(compose, sort_keys=False))
        (self.dir / "plan.json").write_text(json.dumps(self.plan.to_dict(), indent=2) + "\n")

        return self.compose_file

    def up(self, build: bool = True) -> None:
        """Starts the testbed"""

        if build:
            self.build_images()

        self.render()
        self._compose("up", "--detach", "--wait", "--remove-orphans")
        self.network().configure()
        self._log_event("up", spec_hash=self.plan.spec_hash)

    def down(self) -> None:
        """Stops the testbed"""

        if not self.compose_file.exists():
            self.render()

        self._log_event("stopping")
        self._compose("down", "--volumes", "--remove-orphans", "--timeout", "5")
        self._log_event("down")

    def _compose(self, *args: str) -> None:
        cmd = ["docker", "compose", "-p", self.plan.project, "-f", str(self.compose_file), *args]
        subprocess.run(cmd, check=True)

    def containers(self) -> dict[str, Container]:
        found = self.client.containers.list(
            all=True, filters={"label": f"com.docker.compose.project={self.plan.project}"}
        )

        return {c.labels["com.docker.compose.service"]: c for c in found}

    def status(self) -> list[dict[str, Any]]:
        containers = self.containers()
        addr = self.plan.addressing
        rows = []

        for service, c in sorted(containers.items()):
            role = c.labels.get(LABEL_ROLE, "")
            site = c.labels.get(LABEL_SITE, "")
            ip = addr.gateway_ips.get(site) if role == "gateway" else addr.component_ips.get(service)

            rows.append(
                {"service": service, "role": role, "site": site, "ip": str(ip or ""), "state": c.status}
            )

        return rows

    def network(self) -> Network:
        return Network(self.plan, self.containers())

    def set_link(self, name: str, **changes: Any) -> LinkSpec:
        """Changes a link's impairement on a running testbed"""

        if name not in self.scenario.links:
            raise KeyError(f"unknown link {name}")

        current = self.scenario.links[name].model_dump()
        link = LinkSpec.model_validate(current | {k: v for k, v in changes.items() if v is not None})

        self.scenario.links[name] = link
        self.network().apply_link(name, link)
        self._log_event("set_link", link=name, spec=link.model_dump(mode="json"))

        return link

    def _log_event(self, event: str, **fields: Any) -> None:
        line = json.dumps({"t": time.time(), "source": "testbed", "event": event, **fields}) + "\n"
        self.dir.mkdir(parents=True, exist_ok=True)

        with (self.dir / "events.jsonl").open("a") as f:
            f.write(line)
