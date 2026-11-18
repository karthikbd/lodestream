"""Plugin registry. Sources, sinks and steps register themselves by name, so a
config file (or your own plugin module) can pick them dynamically."""
from __future__ import annotations

from typing import Callable, Dict, Type

SOURCES: Dict[str, Type] = {}
SINKS: Dict[str, Type] = {}
STAGES: Dict[str, Type] = {}


def _register(table: Dict[str, Type], name: str) -> Callable[[Type], Type]:
    def deco(cls: Type) -> Type:
        table[name] = cls
        cls.registered_name = name
        return cls
    return deco


def register_source(name: str):
    return _register(SOURCES, name)


def register_sink(name: str):
    return _register(SINKS, name)


def register_stage(name: str):
    return _register(STAGES, name)


def load_builtins() -> None:
    # Importing the modules runs their @register_* decorators.
    from .sources import filesystem, sql_blob, wss_sql, csv_manifest, s3, cmis  # noqa: F401
    from .sinks import local_folder, filenet_graphql  # noqa: F401
    from .stages import inventory, filter, extract, load, verify  # noqa: F401
