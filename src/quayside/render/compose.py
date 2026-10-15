from typing import Any

from quayside.images import GATEWAY, NETCTL
from quayside.render.plan import Plan
from quayside.spec.models import NETCTL_SERVICE, gateway_name

LABEL_ROLE = "org.quayside.role"
LABEL_SITE = "org.quayside.site"
LABEL_HOST = "org.quayside.host"


def _network(plan: Plan, name: str, subnet: str) -> dict[str, Any]:
    return {
        "driver": "bridge",
        "driver_opts": {"com.docker.network.bridge.name": plan.bridge(name)},
        "ipam": {"config": [{"subnet": subnet}]},
    }


def render_compose(plan: Plan) -> dict[str, Any]:
    """Creates a full Docker Compose project based on a plan"""

    scn, addr = plan.scenario, plan.addressing
    networks: dict[str, Any] = {}

    for site in sorted(scn.sites):
        net = plan.site_network(site)
        networks[net] = _network(plan, net, str(addr.site_subnets[site]))

    for link in sorted(scn.links):
        net = plan.link_network(link)
        networks[net] = _network(plan, net, str(addr.link_subnets[link]))

    # Sometimes Docker's DNS doesn't work for some reason, so let's make it explicit
    extra_hosts = {gateway_name(s): str(ip) for s, ip in sorted(addr.gateway_ips.items())}
    extra_hosts |= {name: str(ip) for name, ip in sorted(addr.component_ips.items())}

    services: dict[str, Any] = {}

    for site in sorted(scn.sites):
        services[gateway_name(site)] = _gateway_service(plan, site, extra_hosts)

    for name in sorted(scn.components):
        services[name] = _component_service(plan, name, extra_hosts)

    services[NETCTL_SERVICE] = {
        "image": NETCTL.tag,
        "pull_policy": "never",
        "init": True,
        "privileged": True,
        "pid": "host",
        "network_mode": "host",
        "labels": {LABEL_ROLE: "netctl"},
    }

    return {"name": plan.project, "services": services, "networks": networks}


def _gateway_service(plan: Plan, site: str, extra_hosts: dict[str, str]) -> dict[str, Any]:
    addr = plan.addressing
    networks = {plan.site_network(site): {"ipv4_address": str(addr.gateway_ips[site])}}

    for link in sorted(plan.scenario.links):
        if site in (ips := addr.link_ips[link]):
            networks[plan.link_network(link)] = {"ipv4_address": str(ips[site])}

    return {
        "image": GATEWAY.tag,
        "pull_policy": "never",
        "init": True,
        "hostname": gateway_name(site),
        "networks": networks,
        "sysctls": {
            "net.ipv4.ip_forward": "1",
            "net.ipv4.conf.all.rp_filter": "0",
            "net.ipv4.conf.default.rp_filter": "0",
        },
        "extra_hosts": extra_hosts,
        "labels": {LABEL_ROLE: "gateway", LABEL_SITE: site},
    }


def _component_service(plan: Plan, name: str, extra_hosts: dict[str, str]) -> dict[str, Any]:
    scn, addr = plan.scenario, plan.addressing
    comp = scn.components[name]
    site = scn.site_of(name)

    environment = {
        "QS_COMPONENT": name,
        "QS_SITE": site,
        **({"QS_LAYER": layer} if (layer := scn.layer_of(name)) else {}),
        "QS_SEED": str(plan.component_seed(name)),
        "QS_GATEWAY": str(addr.gateway_ips[site]),
    }

    service: dict[str, Any] = {
        "image": comp.image,
        "init": True,
        "hostname": name,
        "networks": {plan.site_network(site): {"ipv4_address": str(addr.component_ips[name])}},
        "extra_hosts": extra_hosts,
        "environment": environment,
        "labels": {LABEL_ROLE: "component", LABEL_SITE: site, LABEL_HOST: comp.host or ""},
    }

    if comp.command is not None:
        service["command"] = comp.command

    if comp.cap_add:
        service["cap_add"] = sorted(comp.cap_add)

    if comp.cpus is not None:
        service["cpus"] = comp.cpus

    if comp.memory is not None:
        service["mem_limit"] = comp.memory

    return service
