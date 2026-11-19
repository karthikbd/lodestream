"""Plugin registry. Sources, sinks and steps register themselves by name, so a
config file (or your own plugin module) can pick them dynamically."""
from __future__ import annotations

from typing import Any, Callable, Dict, Type

SOURCES: Dict[str, Type[Any]] = {}
SINKS: Dict[str, Type[Any]] = {}
STAGES: Dict[str, Type[Any]] = {}


def _register(table: Dict[str, Type[Any]], name: str) -> Callable[[Type[Any]], Type[Any]]:
    def deco(cls: Type[Any]) -> Type[Any]:
        table[name] = cls
        cls.registered_name = name
        return cls
    return deco


def register_source(name: str) -> Callable[[Type[Any]], Type[Any]]:
    return _register(SOURCES, name)


def register_sink(name: str) -> Callable[[Type[Any]], Type[Any]]:
    return _register(SINKS, name)


def register_stage(name: str) -> Callable[[Type[Any]], Type[Any]]:
    return _register(STAGES, name)


def load_builtins() -> None:
    # Importing the modules runs their @register_* decorators.
    from .sources import filesystem, sql_blob, wss_sql, csv_manifest, s3, cmis
    from .sinks import local_folder, filenet_graphql
    from .stages import inventory, filter, extract, load, verify
