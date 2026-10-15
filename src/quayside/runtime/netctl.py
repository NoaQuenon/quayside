import json
from ipaddress import IPv4Address

from docker.models.containers import Container


class NetCtlError(RuntimeError):
    """Raised for all errors related to interactions with the NetCtl container"""


class NetCtl:
    def __init__(self, helper: Container):
        self.helper = helper

    def host(self, argv: list[str], check: bool = True) -> str:
        """Runs a command in the host network namespace"""
        return self._exec(argv, check)

    def run(self, target: Container, argv: list[str], check: bool = True) -> str:
        """Runs a command in `target`'s network namespace"""

        target.reload()
        pid = target.attrs["State"]["Pid"]

        if not pid:
            raise NetCtlError(f"container {target.name} is not running")

        return self._exec(["nsenter", "-t", str(pid), "-n", "--", *argv], check)

    def interface_for(self, target: Container, ip: IPv4Address) -> str:
        """Returns the name of the interface in `target` that carries `ip`"""

        out = self.run(target, ["ip", "-j", "-4", "addr", "show"])

        for iface in json.loads(out):
            for info in iface.get("addr_info", []):
                if info.get("local") == str(ip):
                    return str(iface["ifname"])

        raise NetCtlError(f"{target.name} has no interface with address {ip}")

    def _exec(self, argv: list[str], check: bool) -> str:
        code, output = self.helper.exec_run(argv)
        assert isinstance(output, bytes)  # To satisfy mypy...
        text = output.decode(errors="replace")

        if check and code != 0:
            raise NetCtlError(f"{' '.join(argv)} failed ({code}): {text.strip()}")

        return text
