from collections.abc import Iterator
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network

from quayside.spec.models import Scenario

GATEWAY_OFFSET = 2
FIRST_COMPONENT_OFFSET = 10


@dataclass
class Addressing:
    site_subnets: dict[str, IPv4Network]
    link_subnets: dict[str, IPv4Network]
    gateway_ips: dict[str, IPv4Address]
    link_ips: dict[str, dict[str, IPv4Address]]
    component_ips: dict[str, IPv4Address]


# Basically our own little DHCP :)
def _free_subnets(pool: Iterator[IPv4Network], taken: list[IPv4Network]) -> Iterator[IPv4Network]:
    for candidate in pool:
        if not any(candidate.overlaps(t) for t in taken):
            yield candidate


def allocate(scn: Scenario) -> Addressing:
    pool = scn.address_pool

    if pool.prefixlen > 23:
        raise ValueError(f"address pool {pool} is too small; use at least a /23")

    link_block = list(pool.subnets(new_prefix=24))[-1]

    site_explicit = [site.subnet for site in scn.sites.values() if site.subnet]
    link_explicit = [link.subnet for link in scn.links.values() if link.subnet]
    explicit = site_explicit + link_explicit

    for a_i, a in enumerate(explicit):
        for b in explicit[a_i + 1 :]:
            if a.overlaps(b):
                raise ValueError(f"explicit subnets {a} and {b} overlap")

    # Sites
    site_pool = _free_subnets((s for s in pool.subnets(new_prefix=24) if s != link_block), explicit)
    site_subnets = {}

    for name in sorted(scn.sites):
        subnet = scn.sites[name].subnet or next(site_pool, None)

        if subnet is None:
            raise ValueError(f"address pool {pool} has no room left for site {name}")

        if subnet.prefixlen > 26:
            raise ValueError(f"site {name} subnet {subnet} is too small; use at least a /26")

        site_subnets[name] = subnet

    # Links

    link_pool = _free_subnets(link_block.subnets(new_prefix=29), explicit)
    link_subnets = {}
    link_ips = {}

    for name in sorted(scn.links):
        link = scn.links[name]
        subnet = link.subnet or next(link_pool, None)

        if subnet is None:
            raise ValueError(f"no room left for link {name} in {link_block}")

        if subnet.prefixlen > 29:
            raise ValueError(f"link {name} subnet {subnet} is too small; use at least a /29")

        link_subnets[name] = subnet
        link_ips[name] = {link.a: subnet[2], link.b: subnet[3]}

    # Gateways
    gateway_ips = {name: subnet[GATEWAY_OFFSET] for name, subnet in site_subnets.items()}

    # Components
    component_ips = {}
    used = {s: set() for s in scn.sites}

    for name in sorted(scn.components):
        ip = scn.components[name].ip

        if ip is None:
            continue

        site = scn.site_of(name)
        subnet = site_subnets[site]

        if ip not in subnet or int(ip) - int(subnet.network_address) < FIRST_COMPONENT_OFFSET:
            raise ValueError(
                f"component {name} ip {ip} must be in subnet {subnet} at offset >= {FIRST_COMPONENT_OFFSET}"
            )

        if ip in used[site]:
            raise ValueError(f"component {name} ip {ip} is already taken")

        used[site].add(ip)
        component_ips[name] = ip

    for name in sorted(scn.components):
        if name in component_ips:
            continue

        site = scn.site_of(name)
        subnet = site_subnets[site]
        hosts = (subnet[i] for i in range(FIRST_COMPONENT_OFFSET, subnet.num_addresses - 1))
        ip = next((h for h in hosts if h not in used[site]), None)

        if ip is None:
            raise ValueError(f"site {site} subnet {subnet} is full")

        used[site].add(ip)
        component_ips[name] = ip

    return Addressing(site_subnets, link_subnets, gateway_ips, link_ips, component_ips)
