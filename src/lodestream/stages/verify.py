"""verify: check every LOADED item in the target and write a reconciliation report."""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from ..models import Status
from ..registry import register_stage
from ..utils import Progress, to_iso, utcnow
from .base import Stage


@register_stage("verify")
class VerifyStage(Stage):
    """Checks every LOADED item in the target (existence, size, checksum where the sink can) and
    writes a reconciliation report.

        [[steps]]
        name = "verify"
        workers = 8
        cleanup_staging = true              # delete staged copies once verified
        report = "./lodestream-report.json"
    """

    description = "Check loaded items exist in the target with the right size/checksum; write a reconciliation report."
    chunkable = True

    def run(self, ctx, limit: Optional[int] = None):
        workers = int(self.options.get("workers", 8))
        cleanup = self.options.get("cleanup_staging", True)
        ctx.open_sink()
        prog = Progress("verify")

        def check(rec):
            try:
                ok, msg = ctx.sink.verify(rec)
            except Exception as exc:  # noqa: BLE001
                ok, msg = False, f"{type(exc).__name__}: {exc}"
            if ok:
                if cleanup and rec.staged_path and os.path.exists(rec.staged_path):
                    os.remove(rec.staged_path)
                prog.add(1, rec.size)
                return {"source_id": rec.source_id, "status": Status.VERIFIED, "error": None,
                        "staged_path": None if cleanup else rec.staged_path}
            prog.add(failed=1)
            return {"source_id": rec.source_id, "status": Status.MISMATCH, "error": f"verify: {msg}"}

        with ThreadPoolExecutor(max_workers=workers) as ex:
            for page in ctx.manifest.iter_records([Status.LOADED], page=workers * 16):
                if ctx.stop_event.is_set():
                    break
                ctx.manifest.update(list(ex.map(check, page)))
        s = prog.summary()
        report_path = ctx.path(self.options.get("report", "lodestream-report.json"))
        counts = ctx.manifest.counts()
        report = {
            "generated_at": to_iso(utcnow()) + "Z",
            "totals": {k: {"count": c, "bytes": b} for k, (c, b) in counts.items()},
            "by_partition": ctx.manifest.partition_counts(),
            "this_run": {"verified": s["docs"], "mismatch": s["failed"]},
        }
        os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        return {"processed": s["docs"] + s["failed"], "verified": s["docs"], "mismatch": s["failed"],
                "seconds": s["seconds"], "report": report_path}
