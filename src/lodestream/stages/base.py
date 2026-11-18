"""Step (stage) contract. Steps are chosen by name at run time."""
from __future__ import annotations

from typing import Any, Dict, Optional


class Stage:
    registered_name = ""
    description = ""
    writes_target = False   # skipped in --dry-run
    chunkable = False       # takes part in `rolling` chunk loops

    def __init__(self, options: Optional[Dict[str, Any]] = None):
        self.options = options or {}

    def run(self, ctx, limit: Optional[int] = None) -> Dict[str, Any]:  # pragma: no cover
        raise NotImplementedError
