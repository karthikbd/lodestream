"""Config loading with ${ENV_VAR} expansion.

* ``.toml`` – read with the standard library's ``tomllib`` (Python 3.11+).
* ``.json`` – any Python version.
* ``.yaml`` / ``.yml`` – only if PyYAML is *already installed*; lodestream never installs it.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Tuple

class ConfigError(ValueError):
    pass


_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

DEFAULT_STEPS = ["inventory", "filter", "extract", "load", "verify"]

# Every key accepted at the top level of a config file (unknown keys are rejected).
TOP_LEVEL_KEYS = ("name", "manifest", "plugins", "source", "sink", "mapping", "steps", "rolling", "hooks")
# Keys accepted in the ``[mapping]`` section.
MAPPING_KEYS = ("default_class", "classes", "properties", "passthrough_unmapped", "title_property", "folder",
                "strip_path_prefixes")


def check_keys(data: Dict[str, Any], allowed: Tuple[str, ...], where: str) -> None:
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        raise ConfigError(f"unknown key(s) in {where}: {', '.join(unknown)}. Allowed: {', '.join(allowed)}")


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


def load_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    lower = path.lower()
    if lower.endswith(".json"):
        data = json.loads(text)
    elif lower.endswith((".yaml", ".yml")):
        try:
            import yaml  # optional: used only if already installed
        except ImportError:
            raise ConfigError("YAML configs need PyYAML, which lodestream does not install. "
                              "Use a .toml or .json config instead.") from None
        data = yaml.safe_load(text) or {}
    else:
        try:
            import tomllib  # Python 3.11+
        except ModuleNotFoundError:  # pragma: no cover - Python 3.10
            raise ConfigError("TOML configs need Python 3.11+; use a .json config instead") from None
        data = tomllib.loads(text)
    return _expand(data)


def normalize_steps(steps: Any) -> List[Tuple[str, Dict[str, Any]]]:
    """Accepts:  ["inventory", "load"]
                 [{"inventory": {...}}, {"load": {...}}]
                 [{"name": "load", "workers": 8}]"""
    out: List[Tuple[str, Dict[str, Any]]] = []
    for item in steps or DEFAULT_STEPS:
        if isinstance(item, str):
            out.append((item, {}))
        elif isinstance(item, dict) and "name" in item:
            opts = {k: v for k, v in item.items() if k != "name"}
            out.append((item["name"], opts))
        elif isinstance(item, dict) and len(item) == 1:
            name, opts = next(iter(item.items()))
            out.append((name, dict(opts or {})))
        else:
            raise ValueError(f"Cannot understand step entry: {item!r}")
    return out
