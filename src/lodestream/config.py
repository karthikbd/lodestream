"""Config loading (YAML or JSON) with ${ENV_VAR} expansion."""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Tuple

_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

DEFAULT_STEPS = ["inventory", "filter", "extract", "load", "verify"]


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
    if path.endswith((".yaml", ".yml")):
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("PyYAML is required for YAML configs: pip install pyyaml") from exc
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text)
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
