from pathlib import Path
from typing import Any

import yaml

from quayside.spec.models import Scenario


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)

    for key, value in patch.items():
        if value is None:
            merged.pop(key, None)

        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)

        else:
            merged[key] = value

    return merged


def load_raw(path: Path, _seen: tuple[Path, ...] = ()) -> dict[str, Any]:
    """Loads a scenario file into one mapping"""
    path = path.resolve()

    if path in _seen:
        chain = " -> ".join(str(p) for p in (*_seen, path))
        raise ValueError(f"circular extends: {chain}")

    data = yaml.safe_load(path.read_text()) or {}

    if not isinstance(data, dict):
        raise ValueError(f"{path}: scenario must be a mapping")

    # We ignore keys starting with 'x-' to allow the use of anchors and stuff
    data = {k: v for k, v in data.items() if not str(k).startswith("x-")}
    bases = data.pop("extends", None) or []

    if isinstance(bases, str):
        bases = [bases]

    merged: dict[str, Any] = {}

    for base in bases:
        merged = deep_merge(merged, load_raw(path.parent / base, (*_seen, path)))

    return deep_merge(merged, data)


def apply_override(data: dict[str, Any], assignment: str) -> dict[str, Any]:
    """Apply a custom assignment to the original data"""
    key, sep, raw = assignment.partition("=")

    if not sep or not key:
        raise ValueError(
            f"override {assignment} must look like YAML (e.g. 'links.factory-edge.latency=20ms')"
        )

    *parents, leaf = key.split(".")
    patch: dict[str, Any] = {leaf: yaml.safe_load(raw)}

    for parent in reversed(parents):
        patch = {parent: patch}

    return deep_merge(data, patch)


def load_scenario(path: str | Path, overrides: list[str] | tuple[str, ...] = ()) -> Scenario:
    """Builds a scenario instance from a YAML file, applying optionnal overrides in the process"""
    data = load_raw(Path(path))

    for assignment in overrides:
        data = apply_override(data, assignment)

    return Scenario.model_validate(data)
