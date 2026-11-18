"""load: create documents (and versions, in order) in the target, in parallel batches."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from typing import List, Optional, Tuple

from ..models import DocumentRecord, Status
from ..registry import register_stage
from ..sinks.base import LoadItem
from ..utils import Progress, log
from .base import Stage

_DONE = (Status.LOADED, Status.VERIFIED, Status.MISMATCH)

Chain = Tuple[Optional[str], List[DocumentRecord]]  # (target id of last loaded version, versions to load)


class _Series:
    """Progress of one version series inside a worker task."""

    __slots__ = ("prev", "chain", "pos")

    def __init__(self, prev: Optional[str], chain: List[DocumentRecord]):
        self.prev, self.chain, self.pos = prev, chain, 0

    @property
    def current(self) -> DocumentRecord:
        return self.chain[self.pos]

    @property
    def active(self) -> bool:
        return self.pos < len(self.chain)

    def stop(self) -> None:
        self.pos = len(self.chain)


@register_stage("load")
class LoadStage(Stage):
    """options:
        workers: 16                 # parallel loader threads (scale with CPE nodes)
        batch_size: 50              # documents per API round trip
        max_batch_mb: 256           # large files go in smaller batches
        series_per_task: 50         # version series handed to a worker at once
        max_attempts: 3
        retry_failed: true          # pick up FAILED items with attempts < max_attempts
    Versions of one document are always loaded oldest -> newest; different
    documents load fully in parallel."""

    description = "Create documents/versions in the target in parallel, batched API calls (streams from source if extract was skipped)."
    writes_target = True
    chunkable = True

    def _statuses(self, ctx) -> List[Status]:
        st = [Status.EXTRACTED]
        if "extract" not in ctx.step_names:
            st.append(Status.PENDING)  # stream mode: read straight from the source
        if self.options.get("retry_failed", True):
            st.append(Status.FAILED)
        return st

    @staticmethod
    def _chain(records: List[DocumentRecord], statuses, max_attempts: int) -> Chain:
        prev: Optional[str] = None
        chain: List[DocumentRecord] = []
        for r in records:
            if r.status == Status.SKIPPED:
                continue
            if r.status in _DONE:
                if chain:
                    break
                prev = r.target_id
                continue
            if r.status in statuses and not (r.status == Status.FAILED and r.attempts >= max_attempts):
                chain.append(r)
            else:
                break  # an older version is not ready yet: keep order, wait
        return prev, chain

    def run(self, ctx, limit: Optional[int] = None):
        o = self.options
        workers = int(o.get("workers", 8))
        batch_size = int(o.get("batch_size", 50))
        max_batch_bytes = int(float(o.get("max_batch_mb", 256)) * 1024 * 1024)
        per_task = int(o.get("series_per_task", batch_size))
        max_attempts = int(o.get("max_attempts", 3))
        statuses = self._statuses(ctx)
        ctx.open_sink()
        prog = Progress("load")
        lock = threading.Lock()
        mismatches = [0]

        def make_item(rec: DocumentRecord, prev: Optional[str]) -> LoadItem:
            cls, props, folder = ctx.mapper.map(rec)
            if rec.staged_path:
                opener = lambda p=rec.staged_path: open(p, "rb")  # noqa: E731
            else:
                opener = lambda r=rec: ctx.source.open_content(r)  # noqa: E731
            return LoadItem(rec, cls, props, folder, prev, opener)

        def sub_batches(items: List[LoadItem]):
            batch: List[LoadItem] = []
            size = 0
            for it in items:
                if batch and (len(batch) >= batch_size or size + it.record.size > max_batch_bytes):
                    yield batch
                    batch, size = [], 0
                batch.append(it)
                size += it.record.size
            if batch:
                yield batch

        def work(chains: List[Chain]) -> None:
            state = [_Series(prev, chain) for prev, chain in chains]
            while state and not ctx.stop_event.is_set():
                items: List[Tuple[_Series, LoadItem]] = []
                for entry in state:
                    rec = entry.current
                    try:
                        items.append((entry, make_item(rec, entry.prev)))
                    except Exception as exc:  # noqa: BLE001  (mapping error)
                        ctx.manifest.update([{"source_id": rec.source_id, "status": Status.FAILED,
                                              "attempts": rec.attempts + 1, "error": f"mapping: {exc}"}])
                        prog.add(failed=1)
                        entry.stop()
                by_id = {it.record.source_id: entry for entry, it in items}
                for batch in sub_batches([it for _, it in items]):
                    try:
                        results = ctx.sink.load_batch(batch)
                    except Exception as exc:  # noqa: BLE001
                        results = [type("R", (), {"source_id": it.record.source_id, "target_id": None,
                                                  "error": f"{type(exc).__name__}: {exc}"})() for it in batch]
                    updates, ok, failed, nbytes = [], 0, 0, 0
                    items_by_id = {it.record.source_id: it for it in batch}
                    for res in results:
                        it = items_by_id[res.source_id]
                        entry = by_id[res.source_id]
                        rec = it.record
                        if res.target_id and not res.error:
                            read = it.reader.bytes_read if it.reader else rec.size
                            digest = it.reader.hexdigest if it.reader else None
                            status, err = Status.LOADED, None
                            if rec.checksum and digest and digest != rec.checksum:
                                status, err = Status.MISMATCH, "checksum changed between extract and load"
                                with lock:
                                    mismatches[0] += 1
                            updates.append({"source_id": rec.source_id, "status": status, "error": err,
                                            "target_id": res.target_id, "size": read,
                                            "checksum": rec.checksum or digest})
                            entry.prev = res.target_id
                            entry.pos += 1
                            ok += 1
                            nbytes += read
                        else:
                            updates.append({"source_id": rec.source_id, "status": Status.FAILED,
                                            "attempts": rec.attempts + 1, "error": f"load: {res.error}"})
                            entry.stop()  # later versions of this series wait
                            failed += 1
                    ctx.manifest.update(updates)
                    prog.add(ok, nbytes, failed)
                state = [e for e in state if e.active]

        submitted_docs = 0
        with ThreadPoolExecutor(max_workers=workers) as ex:
            inflight = set()
            for series_page in ctx.manifest.iter_series(statuses, page=per_task * workers):
                if ctx.stop_event.is_set() or (limit and submitted_docs >= limit):
                    break
                grouped = ctx.manifest.series_records(series_page)
                chains = [c for c in (self._chain(grouped[s], statuses, max_attempts) for s in series_page) if c[1]]
                for i in range(0, len(chains), per_task):
                    task = chains[i:i + per_task]
                    submitted_docs += sum(len(c[1]) for c in task)
                    inflight.add(ex.submit(work, task))
                    if len(inflight) >= workers * 2:
                        done, inflight = wait(inflight, return_when=FIRST_COMPLETED)
                        for f in done:
                            f.result()
                    if limit and submitted_docs >= limit:
                        break
            for f in inflight:
                f.result()
        s = prog.summary()
        if s["failed"]:
            log.warning("[load] %d item(s) failed; see `lodestream status` and `lodestream retry`", s["failed"])
        return {"processed": s["docs"] + s["failed"], "loaded": s["docs"], "failed": s["failed"],
                "mismatch": mismatches[0], "bytes": s["bytes"], "seconds": s["seconds"],
                "docs_per_sec": s["docs_per_sec"], "mb_per_sec": s["mb_per_sec"]}
