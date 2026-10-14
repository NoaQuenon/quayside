import re
from ipaddress import IPv4Address, IPv4Network
from typing import Self

import networkx as nx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from quayside.spec.units import Memory, Milliseconds, Rate

NAME_PATTERN = r"^[a-z][a-z0-9-]{0,39}$"
NETCTL_SERVICE = "netctl"


# Just to avoid typing forbid everywhere
class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SiteSpec(_Model):
    layer: str | None = Field(default=None, pattern=NAME_PATTERN)
    subnet: IPv4Network | None = None
    hub: bool = True


class HostSpec(_Model):
    site: str
    cpus: float | None = Field(default=None, gt=0)
    memory: Memory | None = None


class LinkSpec(_Model):
    a: str
    b: str
    latency: Milliseconds = Field(default=0, ge=0)
    jitter: Milliseconds = Field(default=0, ge=0)
    loss: float = Field(default=0, ge=0, le=100)
    rate: Rate | None = None
    subnet: IPv4Network | None = None

    @model_validator(mode="after")
    def _distinct_ends(self) -> Self:
        if self.a == self.b:
            raise ValueError(f"link endpoints must differ (both are {self.a})")

        return self


class ComponentSpec(_Model):
    image: str
    command: str | list[str] | None = None
    site: str | None = None
    host: str | None = None
    ip: IPv4Address | None = None
    cpus: float | None = Field(default=None, gt=0)
    memory: Memory | None = None
    cap_add: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _placed_once(self) -> Self:
        # A neat little XOR suggestion by Claude, I like it
        if (self.site is None) == (self.host is None):
            raise ValueError("a component needs exactly one of 'site' or 'host'")

        return self


class Scenario(_Model):
    name: str = Field(pattern=NAME_PATTERN)
    description: str = ""
    seed: int = 0
    address_pool: IPv4Network = IPv4Network("10.77.0.0/16")
    sites: dict[str, SiteSpec]
    hosts: dict[str, HostSpec] = Field(default_factory=dict)  # Otherwise all scenarios share the same dict
    links: dict[str, LinkSpec] = Field(default_factory=dict)
    components: dict[str, ComponentSpec] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_names(self) -> Self:
        for kind in ("sites", "hosts", "links", "components"):
            for name in getattr(self, kind):
                if not re.match(NAME_PATTERN, name):
                    raise ValueError(f"{kind[:-1]} name {name} must match {NAME_PATTERN}")

        reserved = {gateway_name(s) for s in self.sites} | {NETCTL_SERVICE}

        if conflict := reserved & set(self.components):
            raise ValueError(f"component names {sorted(conflict)} are reserved")

        return self

    @model_validator(mode="after")
    def _check_references(self) -> Self:
        if not self.sites:
            raise ValueError("a scenario needs at least one site")

        # Hosts
        for name, host in self.hosts.items():
            if host.site not in self.sites:
                raise ValueError(f"host {name} references unknown site {host.site}")

        # Links
        # We need frozenset to allow a tuple to be a key in a dict
        # Again, we love Python
        pairs: dict[frozenset[str], str] = {}

        for name, link in self.links.items():
            for end in (link.a, link.b):
                if end not in self.sites:
                    raise ValueError(f"link {name} references unknown site {end}")

            pair = frozenset((link.a, link.b))

            if pair in pairs:
                raise ValueError(f"links {pairs[pair]} and {name} connect the same sites")

            pairs[pair] = name

        # Components
        for name, comp in self.components.items():
            if comp.host is not None and comp.host not in self.hosts:
                raise ValueError(f"component {name} references unknown host {comp.host}")

            if comp.site is not None and comp.site not in self.sites:
                raise ValueError(f"component {name} references unknown site {comp.site}")

        # Connected graph
        graph = self.site_graph()

        if not nx.is_connected(graph):
            parts = [sorted(c) for c in nx.connected_components(graph)]
            raise ValueError(f"sites are not all connected by links: {parts}")

        return self

    def layer_of(self, component: str) -> str | None:
        """Returns the layer `component` is part of"""
        comp_site = self.site_of(component)
        return self.sites[comp_site].layer

    def site_of(self, component: str) -> str:
        """Returns the site `component` is part of"""
        comp = self.components[component]

        # Since either comp.site or comp.host is not None, if the first part fails,
        # the second is guaranteed to succeed (at least I hope so)
        return comp.site if comp.site is not None else self.hosts[comp.host].site  # type: ignore[index]

    def site_graph(self) -> nx.Graph[str]:
        """Computes an undirected site graph, with latency as weight"""
        graph: nx.Graph[str] = nx.Graph()
        graph.add_nodes_from(sorted(self.sites))

        for name in sorted(self.links):
            link = self.links[name]
            graph.add_edge(link.a, link.b, link=name, latency=link.latency)

        return graph

    def site_paths(self) -> dict[str, dict[str, list[str]]]:
        """Small helper that calls `site_paths` on the scenario"""
        return site_paths(self.site_graph())


def site_paths(graph: nx.Graph[str]) -> dict[str, dict[str, list[str]]]:
    """Computes the lowest-latency path between every pair of sites"""
    weighted: nx.Graph[str] = nx.Graph()
    weighted.add_nodes_from(sorted(graph))

    for u, v in sorted(graph.edges):
        weighted.add_edge(
            u, v, weight=graph.edges[u, v]["latency"] + 1e-6
        )  # To avoid zero-weight edges (otherwise we have infinite loops)

    return dict(nx.all_pairs_dijkstra_path(weighted))


def gateway_name(site: str) -> str:
    return f"gw-{site}"
