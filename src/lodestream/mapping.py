"""Maps a source record to a target document class, properties and folder."""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

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
        out = dt.strftime("%Y-%m-%dT%H:%M:%SZ") if kind == "datetime" else dt.strftime("%Y-%m-%d")
    else:
        raise ValueError(f"Unknown property type {kind!r}")
    max_len = spec.get("max_length")
    if max_len and isinstance(out, str):
        out = out[: int(max_len)]
    return out


class Mapper:
    """Config example::

        mapping:
          default_class: Document
          classes: {Invoices: Invoice, "Contracts": Contract}   # source content_type -> class
          properties:
            Title: DocumentTitle
            InvoiceDate: {target: InvoiceDate, type: datetime}
            _source_id: MigrationSourceId                      # built-in fields start with _
          passthrough_unmapped: false
          title_property: DocumentTitle
          folder: "/Migrated/{partition}/{directory}"           # null = do not file in a folder
          strip_path_prefixes: ["sites/finance/"]
    """

    def __init__(self, cfg: Optional[Dict[str, Any]] = None):
        cfg = cfg or {}
        self.default_class = cfg.get("default_class", "Document")
        self.classes = cfg.get("classes", {}) or {}
        self.properties: Dict[str, Dict[str, Any]] = {}
        for src, spec in (cfg.get("properties") or {}).items():
            self.properties[src] = {"target": spec} if isinstance(spec, str) else dict(spec)
        self.passthrough = bool(cfg.get("passthrough_unmapped", False))
        self.title_property = cfg.get("title_property", "DocumentTitle")
        self.folder = cfg.get("folder")
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
            v = values.get(src, spec.get("default"))
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
