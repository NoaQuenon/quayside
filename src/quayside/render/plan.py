import hashlib
import json
from dataclasses import dataclass
from functools import cached_property
from typing import Any

from quayside.render.addressing import Addressing, allocate
from quayside.render.routing import Route, gateway_routes
from quayside.spec.models import Scenario


def _short_hash(*parts: str) -> str:
    return hashlib.sha256("/".join(parts).encode()).hexdigest()[:8]


@dataclass(frozen=True)
class Plan:
    scenario: Scenario
    addressing: Addressing
    routes: dict[str, list[Route]]

    @property
    def project(self) -> str:
        return f"qs-{self.scenario.name}"

    @cached_property  # Just discovered this decorator, functools is such a good package
    def spec_hash(self) -> str:
        # Produces a deterministic JSON representation
        scn = self.scenario.model_dump(mode="json")
        canonical = json.dumps(scn, sort_keys=True)

        return hashlib.sha256(canonical.encode()).hexdigest()

    def site_network(self, site: str) -> str:
        return f"site-{site}"

    def link_network(self, link: str) -> str:
        return f"link-{link}"

    def bridge(self, network: str) -> str:
        return f"qs-{_short_hash(self.project, network)}"

    def component_seed(self, component: str) -> int:
        """Computes a per-component deterministic seed derived from the scenario seed"""
        # Thx Claude for this thing
        digest = hashlib.sha256(f"{self.scenario.seed}/{component}".encode()).digest()
        return int.from_bytes(digest[:8], "big") >> 1

    def to_dict(self) -> dict[str, Any]:
        addr = self.addressing

        return {
            "project": self.project,
            "spec_hash": self.spec_hash,
            "scenario": self.scenario.model_dump(mode="json"),
            "sites": {
                site: {
                    "subnet": str(addr.site_subnets[site]),
                    "gateway": str(addr.gateway_ips[site]),
                    "bridge": self.bridge(self.site_network(site)),
                    "routes": [
                        {"destination": str(r.destination), "via": str(r.via), "link": r.link}
                        for r in self.routes[site]
                    ],
                }
                for site in sorted(self.scenario.sites)
            },
            "links": {
                link: {
                    "subnet": str(addr.link_subnets[link]),
                    "ips": {site: str(ip) for site, ip in addr.link_ips[link].items()},
                }
                for link in sorted(self.scenario.links)
            },
            "components": {
                name: {
                    "site": self.scenario.site_of(name),
                    "layer": self.scenario.layer_of(name),
                    "ip": str(ip),
                    "seed": self.component_seed(name),
                }
                for name, ip in sorted(addr.component_ips.items())
            },
        }


def build_plan(scn: Scenario) -> Plan:
    addressing = allocate(scn)
    routes = gateway_routes(scn, addressing)

    return Plan(scn, addressing, routes)
