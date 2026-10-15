from quayside.spec.models import LinkSpec


def is_impaired(link: LinkSpec) -> bool:
    return bool(link.latency or link.jitter or link.loss or link.rate)


def netem_command(link: LinkSpec, dev: str) -> list[str]:
    """Returns the `tc` command that shapes egress on `dev` according to `link`"""

    argv = ["tc", "qdisc", "replace", "dev", dev, "root", "netem"]

    if link.latency or link.jitter:
        argv += ["delay", f"{link.latency}ms"]

        if link.jitter:
            argv += [f"{link.jitter}ms", "distribution", "normal"]

    if link.loss:
        argv += ["loss", f"{link.loss}%"]

    if link.rate:
        argv += ["rate", link.rate]

    # Default limit is 1000, couldn't hurt to bump that
    argv += ["limit", "100000"]

    return argv


def clear_command(dev: str) -> list[str]:
    return ["tc", "qdisc", "del", "dev", dev, "root"]
