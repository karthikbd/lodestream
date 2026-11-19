"""Maps a source record to a target document class, properties and folder."""
from __future__ import annotations

import re
import string
from typing import Any, Dict, Optional, Tuple

from .config import MAPPING_KEYS, ConfigError, check_keys
from .models import DocumentRecord
from .utils import require_dt


class _SafeDict(dict):
    def __missing__(self, key):
        return ""


def _convert(value: Any, spec: Dict[str, Any]) -> Any:
    kind = (spec.get("type") or "").lower()
    if kind in ("", "auto"):
        out = value
    elif kind in ("string", "str"):
        out = str(value)
    elif kind in ("int", "integer"):
        out = int(float(value))
    elif kind in ("float", "double"):
        out = float(value)
    elif kind in ("bool", "boolean"):
        out = value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "yes", "y")
    elif kind in ("datetime", "date"):
        dt = require_dt(value)
        out = dt.replace(microsecond=0).isoformat() + "Z" if kind == "datetime" else dt.date().isoformat()
    else:
        raise ValueError(f"Unknown property type {kind!r}")
    max_len = spec.get("max_length")
    if max_len and isinstance(out, str):
        out = out[: int(max_len)]
    return out


_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _check_template(template: str) -> None:
    """Folder templates may only use plain ``{field}`` placeholders (no indexing, attributes,
    format specs or conversions), so a bad template fails at start-up, not on every document."""
    try:
        parts = list(string.Formatter().parse(template))
    except ValueError as exc:
        raise ConfigError(f"[mapping] folder template {template!r}: {exc} (use {{{{ and }}}} for literal braces)") from None
    for _, name, spec, conv in parts:
        if name is None:
            continue
        if not _FIELD.fullmatch(name) or spec or conv:
            raise ConfigError(f"[mapping] folder template {template!r}: placeholder {{{name}{':' + spec if spec else ''}}} "
                              "is not allowed; use plain names such as {directory}, {partition}, {content_type}, "
                              "{name} or a property name")


class Mapper:
    """Maps a source record to a target class, properties and folder.

    Example ``[mapping]`` section::

        [mapping]
        default_class = "Document"
        title_property = "DocumentTitle"
        folder = "/Migrated/{partition}/{directory}"   # omit = do not file in a folder
        strip_path_prefixes = ["sites/finance"]
        passthrough_unmapped = false

        [mapping.classes]                   # source content_type -> class
        Invoices = "Invoice"

        [mapping.properties]                # built-in fields start with _
        Title = "DocumentTitle"
        InvoiceDate = { target = "InvoiceDate", type = "datetime" }
        _source_id = "MigrationSourceId"

    See the Mapping page of the user guide for every field.
    """

    def __init__(self, cfg: Optional[Dict[str, Any]] = None):
        cfg = cfg or {}
        check_keys(cfg, MAPPING_KEYS, "[mapping]")
        self.default_class = cfg.get("default_class", "Document")
        self.classes = cfg.get("classes", {}) or {}
        self.properties: Dict[str, Dict[str, Any]] = {}
        for src, spec in (cfg.get("properties") or {}).items():
            self.properties[src] = {"target": spec} if isinstance(spec, str) else dict(spec)
        self.passthrough = bool(cfg.get("passthrough_unmapped", False))
        self.title_property = cfg.get("title_property", "DocumentTitle")
        self.folder = cfg.get("folder")
        if self.folder:
            _check_template(self.folder)
        self.strip_prefixes = [p.strip("/") for p in cfg.get("strip_path_prefixes", []) or []]

    def _directory(self, record: DocumentRecord) -> str:
        d = (record.directory or "").strip("/")
        for p in self.strip_prefixes:
            if p and (d == p or d.startswith(p + "/")):
                d = d[len(p):].strip("/")
                break
        return d

    def map(self, record: DocumentRecord) -> Tuple[str, Dict[str, Any], Optional[str]]:
        cls = self.classes.get(record.content_type) or self.classes.get("*") or self.default_class
        values = {**record.properties, **record.builtin_fields()}
        out: Dict[str, Any] = {}
        for src, spec in self.properties.items():
            v = values.get(src)
            if v is None or v == "":
                v = spec.get("default")
            if v is None or v == "":
                continue
            out[spec["target"]] = _convert(v, spec)
        if self.passthrough:
            mapped = set(self.properties)
            for k, v in record.properties.items():
                if k not in mapped and not k.startswith("_") and v is not None:
                    out.setdefault(k, v)
        if self.title_property and self.title_property not in out:
            out[self.title_property] = record.name
        folder = None
        if self.folder:
            ctx = _SafeDict(values)
            ctx.update(directory=self._directory(record), partition=record.partition,
                       content_type=record.content_type, name=record.name)
            folder = "/" + re.sub(r"/{2,}", "/", self.folder.format_map(ctx)).strip("/")
        return cls, out, folder
