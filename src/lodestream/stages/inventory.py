"""inventory: scan the source and register every document version as PENDING.
delta:     the same, but only for items changed since the last inventory/delta run."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from typing import Optional

from ..registry import register_stage
from ..utils import Progress, log, parse_dt
from .base import Stage


@register_stage("inventory")
class InventoryStage(Stage):
    description = "Scan the source (partitions in parallel) and register every document/version in the manifest."

    def _since(self, ctx):
        return parse_dt(self.options.get("since")) if self.options.get("since") else None

    def run(self, ctx, limit: Optional[int] = None):
        since = self._since(ctx)
        source = ctx.source
        parts = source.partitions()
        workers = int(self.options.get("workers", 4))
        batch = int(self.options.get("batch_size", 2000))
        prog = Progress(self.registered_name)
        log.info("[%s] %d partition(s), %d worker(s)%s", self.registered_name, len(parts), workers,
                 f", changes since {since}" if since else "")

        def scan(part):
            buf, new, seen = [], 0, 0
            for rec in source.iter_documents(part, since):
                if ctx.stop_event.is_set():
                    break
                rec.partition = rec.partition or part
                buf.append(rec)
                if len(buf) >= batch:
                    new += ctx.manifest.add_records(buf)
                    seen += len(buf)
                    prog.add(len(buf), sum(r.size for r in buf))
                    buf = []
            if buf:
                new += ctx.manifest.add_records(buf)
                seen += len(buf)
                prog.add(len(buf), sum(r.size for r in buf))
            return new, seen

        new_total = seen_total = errors = 0
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(scan, p): p for p in parts}
            for f in as_completed(futures):
                try:
                    n, s = f.result()
                    new_total += n
                    seen_total += s
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    log.error("[%s] partition %r failed: %s", self.registered_name, futures[f], exc)
        s = prog.summary()
        return {"partitions": len(parts), "partition_errors": errors, "seen": seen_total,
                "new": new_total, "processed": seen_total, "seconds": s["seconds"],
                "bytes_seen": s["bytes"], "since": str(since) if since else None}


@register_stage("delta")
class DeltaStage(InventoryStage):
    description = ("Re-scan only items changed since the last inventory/delta run (for the final "
                   "catch-up before cutover). Follow it with filter/extract/load/verify.")

    def _since(self, ctx):
        if self.options.get("since"):
            return parse_dt(self.options["since"])
        last = ctx.manifest.last_run(["inventory", "delta"])
        if not last:
            raise RuntimeError("delta needs a previous inventory run (or an explicit `since`)")
        overlap = float(self.options.get("overlap_minutes", 10))
        return parse_dt(last["started"]) - timedelta(minutes=overlap)
