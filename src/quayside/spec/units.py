import re
from typing import Annotated

from pydantic import BeforeValidator

_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(us|ms|s)?\s*$")
_DURATION_SCALE = {"us": 1e-3, "ms": 1.0, "s": 1e3, None: 1.0}

_RATE = re.compile(r"^\d+(?:\.\d+)?(?:bit|kbit|mbit|gbit|bps|kbps|mbps|gbps)$", re.IGNORECASE)
_MEMORY = re.compile(r"^\d+(?:\.\d+)?[bkmg]?$", re.IGNORECASE)


def parse_ms(value: object) -> float:
    # Apparently Python considers True as a int or a float
    # What a great language
    if isinstance(value, bool):
        raise ValueError(f"invalid duration {value}; expected e.g. '5ms', '1s', '200us'")

    if isinstance(value, int | float):
        return float(value)

    if isinstance(value, str) and (m := _DURATION.match(value)):
        return float(m.group(1)) * _DURATION_SCALE[m.group(2)]

    raise ValueError(f"invalid duration {value}; expected e.g. '5ms', '1s', '200us'")


def check_rate(value: object) -> str:
    if isinstance(value, str) and _RATE.match(value):
        return value.lower()

    raise ValueError(f"invalid rate {value}; expected e.g. '100mbit', '1gbit', '500kbit'")


def check_memory(value: object) -> str:
    if isinstance(value, int):
        return str(value)

    if isinstance(value, str) and _MEMORY.match(value):
        return value.lower()

    raise ValueError(f"invalid memory size {value}; expected e.g. '512m', '1g', '100k'")


Milliseconds = Annotated[float, BeforeValidator(parse_ms)]
Rate = Annotated[str, BeforeValidator(check_rate)]
Memory = Annotated[str, BeforeValidator(check_memory)]
