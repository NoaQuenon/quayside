from docker.models.containers import Container

from quayside.render.plan import Plan
from quayside.runtime.netctl import NetCtl
from quayside.runtime.netem import clear_command, is_impaired, netem_command
from quayside.spec.models import NETCTL_SERVICE, LinkSpec, gateway_name


class Network:
    def __init__(self, plan: Plan, containers: dict[str, Container]):
        self.plan = plan
        self.containers = containers
        self.netctl = NetCtl(containers[NETCTL_SERVICE])

    def gateway(self, site: str) -> Container:
        return self.containers[gateway_name(site)]

    def configure(self) -> None:
        scn = self.plan.scenario

        for site, spec in sorted(scn.sites.items()):
            if spec.hub:
                bridge = self.plan.bridge(self.plan.site_network(site))
                self.netctl.host(["ip", "link", "set", bridge, "type", "bridge", "ageing_time", "0"])

        for site in sorted(scn.sites):
            gw = self.gateway(site)
            self.netctl.run(
                gw, ["ip", "route", "del", "default"], check=False
            )  # Remove Docker's default route to the internet

            for route in self.plan.routes[site]:
                self.netctl.run(gw, ["ip", "route", "replace", str(route.destination), "via", str(route.via)])

        for name, link in sorted(scn.links.items()):
            self.apply_link(name, link)

        for name in sorted(scn.components):
            self.configure_component(name)

    def configure_component(self, name: str) -> None:
        """Points a component's default route at its site gateway"""

        gw_ip = self.plan.addressing.gateway_ips[self.plan.scenario.site_of(name)]
        command = ["ip", "route", "replace", "default", "via", str(gw_ip)]

        self.netctl.run(self.containers[name], command)

    def apply_link(self, name: str, link: LinkSpec) -> None:
        """Applies a link's impairement on both of its gateways"""

        for site, ip in self.plan.addressing.link_ips[name].items():
            gw = self.gateway(site)
            dev = self.netctl.interface_for(gw, ip)

            if is_impaired(link):
                self.netctl.run(gw, netem_command(link, dev))

            else:
                # Better be safe than sorry
                self.netctl.run(gw, clear_command(dev), check=False)
