from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network

from quayside.render.addressing import Addressing
from quayside.spec.models import Scenario


@dataclass
class Route:
    destination: IPv4Network
    via: IPv4Address
    link: str


def gateway_routes(scn: Scenario, addr: Addressing) -> dict[str, list[Route]]:
    graph = scn.site_graph()
    all_paths = scn.site_paths()
    tables = {}

    for src in sorted(scn.sites):
        paths = all_paths[src]
        routes = []

        for dst in sorted(scn.sites):
            if dst == src:
                continue

            next_site = paths[dst][1]
            link = graph.edges[src, next_site]["link"]
            routes.append(Route(addr.site_subnets[dst], addr.link_ips[link][next_site], link))

        tables[src] = routes

    return tables
