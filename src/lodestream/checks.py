"""Pre-flight checks: ``lodestream check -c migration.toml``.

Read-only. Proves, against the *real* systems and before anything is migrated, that:

* the source is reachable, every query it will run is valid for the actual schema (each SQL query
  is executed with ``WHERE 1 = 0``, so a missing table or column fails here, not after days of
  loading), sample records come back, and one document's content can be streamed;
* the target is reachable and authenticated, and (FileNet) every GraphQL operation, argument and
  input field the sink sends exists in the server's own schema, the object store answers, and every
  mapped class and property exists.

Plugins can add their own checks by overriding ``Source.check`` / ``Sink.check``.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class CheckResult:
    area: str          # "source", "sink", "mapping", "config"
    name: str
    status: str        # "ok", "fail", "warn", "skip"
    detail: str = ""
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "warn", "skip")


@dataclass
class CheckContext:
    """Passed to ``Source.check`` / ``Sink.check``."""

    sample: int = 5
    classes: Dict[str, List[str]] = field(default_factory=dict)  # target class -> mapped property names
    folders: List[str] = field(default_factory=list)


def run(area: str, name: str, fn: Callable[[], Any]) -> CheckResult:
    """Run one check; a returned string becomes the detail, an exception a failure."""
    start = time.monotonic()
    try:
        out = fn()
        status, detail = "ok", ""
        if isinstance(out, tuple):
            status, detail = out
        elif out is not None:
            detail = str(out)
        return CheckResult(area, name, status, detail, round(time.monotonic() - start, 2))
    except Exception as exc:
        return CheckResult(area, name, "fail", f"{type(exc).__name__}: {exc}"[:600],
                           round(time.monotonic() - start, 2))


def summarize(results: List[CheckResult]) -> Optional[str]:
    failed = [r for r in results if r.status == "fail"]
    if failed:
        return f"{len(failed)} check(s) failed"
    return None
