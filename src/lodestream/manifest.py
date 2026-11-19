"""The manifest: one row per document version, tracking its migration status.

The manifest is the backbone of the migration. Every step reads work from it and
writes results back, so the whole pipeline is restartable and auditable.
SQLite (WAL mode) is used by default; it comfortably handles 100M+ rows on a
fast local disk. Keep the manifest file on local SSD, not on a network share.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

from .models import DocumentRecord, Status
from .utils import to_iso, utcnow

_COLUMNS = [
    "source_id", "series_id", "version_index", "name", "directory", "size", "modified",
    "content_type", "properties", "source_ref", "partition", "status", "checksum",
    "staged_path", "target_id", "error", "attempts",
]
_UPDATABLE = {
    "status", "checksum", "staged_path", "target_id", "error", "attempts", "size",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    source_id     TEXT PRIMARY KEY,
    series_id     TEXT NOT NULL,
    version_index INTEGER NOT NULL,
    name          TEXT,
    directory     TEXT,
    size          INTEGER DEFAULT 0,
    modified      TEXT,
    content_type  TEXT,
    properties    TEXT,
    source_ref    TEXT,
    partition     TEXT,
    status        TEXT NOT NULL,
    checksum      TEXT,
    staged_path   TEXT,
    target_id     TEXT,
    error         TEXT,
    attempts      INTEGER DEFAULT 0,
    updated_at    TEXT
);
CREATE INDEX IF NOT EXISTS ix_documents_status ON documents(status, source_id);
CREATE INDEX IF NOT EXISTS ix_documents_series ON documents(series_id, version_index);
CREATE INDEX IF NOT EXISTS ix_documents_status_series ON documents(status, series_id);
CREATE TABLE IF NOT EXISTS runs (
    run_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    step     TEXT NOT NULL,
    started  TEXT NOT NULL,
    finished TEXT,
    stats    TEXT
);
"""


def _row_to_record(row: sqlite3.Row) -> DocumentRecord:
    return DocumentRecord(
        source_id=row["source_id"],
        series_id=row["series_id"],
        version_index=row["version_index"],
        name=row["name"] or "",
        directory=row["directory"] or "",
        size=row["size"] or 0,
        modified=row["modified"] or "",
        content_type=row["content_type"] or "",
        properties=json.loads(row["properties"] or "{}"),
        source_ref=json.loads(row["source_ref"] or "{}"),
        partition=row["partition"] or "",
        status=Status(row["status"]),
        checksum=row["checksum"],
        staged_path=row["staged_path"],
        target_id=row["target_id"],
        error=row["error"],
        attempts=row["attempts"] or 0,
    )


def _in(values: Sequence[Any]) -> str:
    return ",".join("?" for _ in values)


class Manifest:
    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=60)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------ helpers
    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def _query(self, sql: str, params: Sequence[Any] = ()) -> List[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ writes
    def add_records(self, records: Iterable[DocumentRecord]) -> int:
        """Insert new records (existing source_ids are left untouched). Returns # inserted."""
        inserted = 0
        now = to_iso(utcnow())
        with self._tx() as conn:
            for r in records:
                vi = r.version_index
                if not vi:
                    if conn.execute("SELECT 1 FROM documents WHERE source_id=?", (r.source_id,)).fetchone():
                        continue
                    vi = conn.execute(
                        "SELECT COALESCE(MAX(version_index), 0) FROM documents WHERE series_id=?",
                        (r.series_id,),
                    ).fetchone()[0] + 1
                cur = conn.execute(
                    f"INSERT OR IGNORE INTO documents ({','.join(_COLUMNS)}, updated_at) "
                    f"VALUES ({_in(_COLUMNS)}, ?)",
                    (
                        r.source_id, r.series_id, vi, r.name, r.directory, r.size, r.modified,
                        r.content_type, json.dumps(r.properties, default=str),
                        json.dumps(r.source_ref, default=str), r.partition, Status.PENDING.value,
                        r.checksum, None, None, None, 0, now,
                    ),
                )
                inserted += cur.rowcount
        return inserted

    def update(self, updates: Iterable[Dict[str, Any]]) -> None:
        """Apply partial updates: each dict needs ``source_id`` plus updatable fields."""
        now = to_iso(utcnow())
        with self._tx() as conn:
            for u in updates:
                fields = {k: (v.value if isinstance(v, Status) else v)
                          for k, v in u.items() if k in _UPDATABLE}
                if not fields:
                    continue
                sets = ", ".join(f"{k}=?" for k in fields)
                conn.execute(
                    f"UPDATE documents SET {sets}, updated_at=? WHERE source_id=?",
                    (*fields.values(), now, u["source_id"]),
                )

    def reset_failed(self, reset_attempts: bool = True) -> int:
        with self._tx() as conn:
            att = ", attempts=0" if reset_attempts else ""
            a = conn.execute(
                f"UPDATE documents SET status='EXTRACTED', error=NULL{att} "
                "WHERE status='FAILED' AND staged_path IS NOT NULL").rowcount
            b = conn.execute(
                f"UPDATE documents SET status='PENDING', error=NULL{att} "
                "WHERE status='FAILED' AND staged_path IS NULL").rowcount
        return int(a + b)

    # ------------------------------------------------------------------ reads
    def iter_records(self, statuses: Sequence[Status], page: int = 1000,
                     limit: Optional[int] = None) -> Iterator[List[DocumentRecord]]:
        """Yield pages of records in the given statuses (keyset pagination)."""
        st = [s.value for s in statuses]
        last, count = "", 0
        while True:
            size = page if limit is None else min(page, limit - count)
            if size <= 0:
                return
            rows = self._query(
                f"SELECT * FROM documents WHERE status IN ({_in(st)}) AND source_id > ? "
                f"ORDER BY source_id LIMIT ?", (*st, last, size))
            if not rows:
                return
            last = rows[-1]["source_id"]
            count += len(rows)
            yield [_row_to_record(r) for r in rows]

    def iter_series(self, statuses: Sequence[Status], page: int = 500) -> Iterator[List[str]]:
        st = [s.value for s in statuses]
        last = ""
        while True:
            rows = self._query(
                f"SELECT DISTINCT series_id FROM documents WHERE status IN ({_in(st)}) "
                f"AND series_id > ? ORDER BY series_id LIMIT ?", (*st, last, page))
            if not rows:
                return
            last = rows[-1][0]
            yield [r[0] for r in rows]

    def series_records(self, series_ids: Sequence[str]) -> Dict[str, List[DocumentRecord]]:
        out: Dict[str, List[DocumentRecord]] = {s: [] for s in series_ids}
        if not series_ids:
            return out
        rows = self._query(
            f"SELECT * FROM documents WHERE series_id IN ({_in(series_ids)}) "
            f"ORDER BY series_id, version_index", list(series_ids))
        for r in rows:
            out[r["series_id"]].append(_row_to_record(r))
        return out

    def top_version_indices(self, series_ids: Sequence[str], n: int) -> Dict[str, Set[int]]:
        out: Dict[str, Set[int]] = {}
        if not series_ids:
            return out
        rows = self._query(
            f"SELECT series_id, version_index FROM documents WHERE series_id IN ({_in(series_ids)}) "
            f"ORDER BY series_id, version_index DESC", list(series_ids))
        for sid, vi in rows:
            bucket = out.setdefault(sid, set())
            if len(bucket) < n:
                bucket.add(vi)
        return out

    def get(self, source_id: str) -> Optional[DocumentRecord]:
        rows = self._query("SELECT * FROM documents WHERE source_id=?", (source_id,))
        return _row_to_record(rows[0]) if rows else None

    def counts(self) -> Dict[str, Tuple[int, int]]:
        rows = self._query("SELECT status, COUNT(*), COALESCE(SUM(size),0) FROM documents GROUP BY status")
        return {r[0]: (r[1], r[2]) for r in rows}

    def partition_counts(self) -> Dict[str, Dict[str, int]]:
        rows = self._query("SELECT partition, status, COUNT(*) FROM documents GROUP BY partition, status")
        out: Dict[str, Dict[str, int]] = {}
        for p, s, c in rows:
            out.setdefault(p or "", {})[s] = c
        return out

    def bytes_in_status(self, status: Status) -> int:
        return int(self._query("SELECT COALESCE(SUM(size),0) FROM documents WHERE status=?", (status.value,))[0][0])

    # ------------------------------------------------------------------ runs
    def start_run(self, step: str) -> int:
        with self._tx() as conn:
            return int(conn.execute("INSERT INTO runs(step, started) VALUES (?, ?)",
                                    (step, to_iso(utcnow()))).lastrowid or 0)

    def finish_run(self, run_id: int, stats: Dict[str, Any]) -> None:
        with self._tx() as conn:
            conn.execute("UPDATE runs SET finished=?, stats=? WHERE run_id=?",
                         (to_iso(utcnow()), json.dumps(stats, default=str), run_id))

    def last_run(self, steps: Sequence[str]) -> Optional[Dict[str, Any]]:
        rows = self._query(
            f"SELECT * FROM runs WHERE step IN ({_in(steps)}) AND finished IS NOT NULL "
            f"ORDER BY run_id DESC LIMIT 1", list(steps))
        if not rows:
            return None
        r = rows[0]
        return {"run_id": r["run_id"], "step": r["step"], "started": r["started"],
                "finished": r["finished"], "stats": json.loads(r["stats"] or "{}")}

    def runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self._query("SELECT * FROM runs ORDER BY run_id DESC LIMIT ?", (limit,))
        return [{"run_id": r["run_id"], "step": r["step"], "started": r["started"],
                 "finished": r["finished"], "stats": json.loads(r["stats"] or "{}")} for r in rows]
