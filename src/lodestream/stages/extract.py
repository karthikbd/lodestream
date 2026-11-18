"""extract: copy content from the source into a staging area and checksum it."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from ..models import Status
from ..registry import register_stage
from ..utils import HashingReader, Progress, human_bytes, log, safe_filename
from .base import Stage


@register_stage("extract")
class ExtractStage(Stage):
    """options:
        staging_dir: /mnt/staging          (required; fast NAS/SSD near FileNet)
        workers: 16
        max_staged_bytes: 5e12             # pause extraction when this much is waiting to load
        max_attempts: 3
    Leave this step out to stream content straight from the source into FileNet."""

    description = "Copy content from source to a fast staging area with SHA-256 checksums (optional; omit to stream directly)."
    writes_target = True
    chunkable = True

    def run(self, ctx, limit: Optional[int] = None):
        staging = ctx.path(self.options.get("staging_dir", "./staging"))
        os.makedirs(staging, exist_ok=True)
        workers = int(self.options.get("workers", 8))
        max_staged = float(self.options.get("max_staged_bytes", 0)) or None
        max_attempts = int(self.options.get("max_attempts", 3))
        prog = Progress("extract")
        processed = 0

        def one(rec):
            sub = os.path.join(staging, safe_filename(rec.series_id)[-2:])
            os.makedirs(sub, exist_ok=True)
            dest = os.path.join(sub, safe_filename(rec.source_id))
            tmp = dest + ".part"
            try:
                with HashingReader(ctx.source.open_content(rec)) as src, open(tmp, "wb") as out:
                    while True:
                        block = src.read(4 * 1024 * 1024)
                        if not block:
                            break
                        out.write(block)
                os.replace(tmp, dest)
                prog.add(1, src.bytes_read)
                return {"source_id": rec.source_id, "status": Status.EXTRACTED, "staged_path": dest,
                        "checksum": src.hexdigest, "size": src.bytes_read, "error": None}
            except Exception as exc:  # noqa: BLE001
                if os.path.exists(tmp):
                    os.remove(tmp)
                prog.add(failed=1)
                return {"source_id": rec.source_id, "status": Status.FAILED, "attempts": rec.attempts + 1,
                        "error": f"extract: {type(exc).__name__}: {exc}"}

        with ThreadPoolExecutor(max_workers=workers) as ex:
            for page in ctx.manifest.iter_records([Status.PENDING], page=workers * 8, limit=limit):
                if ctx.stop_event.is_set():
                    break
                if max_staged and ctx.manifest.bytes_in_status(Status.EXTRACTED) >= max_staged:
                    log.info("[extract] staging holds >= %s; pausing until loads catch up",
                             human_bytes(max_staged))
                    break
                page = [r for r in page if r.attempts < max_attempts]
                ctx.manifest.update(list(ex.map(one, page)))
                processed += len(page)
        s = prog.summary()
        return {"processed": processed, "extracted": s["docs"], "failed": s["failed"], "bytes": s["bytes"],
                "seconds": s["seconds"], "docs_per_sec": s["docs_per_sec"], "mb_per_sec": s["mb_per_sec"]}
