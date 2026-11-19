"""Small helpers: time parsing, hashing, progress reporting, imports."""
from __future__ import annotations

import hashlib
import importlib
import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger("lodestream")

_DT_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d")


def utcnow() -> datetime:
    """Naive UTC 'now' (second precision) used for run bookkeeping."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def parse_dt(value: Any) -> Optional[datetime]:
    """Parse a datetime/ISO string into a naive UTC datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt: Optional[datetime] = None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        for fmt in _DT_FORMATS:
            try:
                dt = datetime.strptime(s[:19], fmt)
                break
            except ValueError:
                continue
    if dt is None:
        raise ValueError(f"Unrecognised date/time: {value!r}")
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def require_dt(value: Any) -> datetime:
    """Like parse_dt, but the value must be present."""
    dt = parse_dt(value)
    if dt is None:
        raise ValueError("A date/time value is required")
    return dt


def to_iso(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        return require_dt(value).replace(microsecond=0).isoformat()   # 4-digit year, even before 1000
    except (ValueError, AttributeError):
        return str(value)


def jsonable(value: Any) -> Any:
    """Coerce DB driver values (datetime, Decimal, UUID...) into JSON-safe values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return to_iso(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return None
    try:
        from decimal import Decimal

        if isinstance(value, Decimal):
            return float(value)
    except ImportError:  # pragma: no cover
        pass
    return str(value)


class HashingReader:
    """Wraps a binary stream, computing SHA-256 and byte count as it is read."""

    def __init__(self, raw):
        self._raw = raw
        self._hash = hashlib.sha256()
        self.bytes_read = 0
        self.eof = False
        self.name = getattr(raw, "name", "content")

    def read(self, n: int = -1) -> bytes:
        data = self._raw.read() if n is None or n < 0 else self._raw.read(n)
        if data:
            self._hash.update(data)
            self.bytes_read += len(data)
        if not data or n is None or n < 0:
            self.eof = True
        return data

    def readable(self) -> bool:
        return True

    @property
    def hexdigest(self) -> Optional[str]:
        return self._hash.hexdigest() if self.eof else None

    def close(self) -> None:
        try:
            self._raw.close()
        except Exception:  # pragma: no cover
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def sha256_file(path: str, chunk: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def short_hash(text: str, n: int = 10) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:n]


def safe_filename(text: str, max_len: int = 120) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or "doc"
    return f"{cleaned[:max_len]}_{short_hash(text)}"


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1024 or unit == "PB":
            return f"{n:,.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"  # pragma: no cover


def human_duration(seconds: float) -> str:
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return f"{d}d {h}h {m}m"
    if h:
        return f"{h}h {m}m"
    return f"{m}m {s}s"


def import_object(path: str) -> Any:
    """Import ``package.module:attribute``."""
    module, _, attr = path.partition(":")
    obj = importlib.import_module(module)
    for part in filter(None, attr.split(".")):
        obj = getattr(obj, part)
    return obj


class Progress:
    """Thread-safe counters with periodic log lines."""

    def __init__(self, label: str, log_every: float = 15.0):
        self.label = label
        self.docs = 0
        self.failed = 0
        self.bytes = 0
        self._start = time.monotonic()
        self._last = self._start
        self._every = log_every
        self._lock = threading.Lock()

    def add(self, docs: int = 0, nbytes: int = 0, failed: int = 0) -> None:
        with self._lock:
            self.docs += docs
            self.bytes += nbytes
            self.failed += failed
            now = time.monotonic()
            if now - self._last >= self._every:
                self._last = now
                s = self._summary_unlocked()
                log.info(
                    "[%s] %s docs ok, %s failed, %s | %.1f docs/s, %.1f MB/s",
                    self.label, f"{s['docs']:,}", f"{s['failed']:,}", human_bytes(s["bytes"]),
                    s["docs_per_sec"], s["mb_per_sec"],
                )

    def _summary_unlocked(self) -> dict:
        elapsed = max(time.monotonic() - self._start, 1e-9)
        return {
            "docs": self.docs,
            "failed": self.failed,
            "bytes": self.bytes,
            "seconds": round(elapsed, 2),
            "docs_per_sec": round(self.docs / elapsed, 2),
            "mb_per_sec": round(self.bytes / elapsed / 1e6, 2),
        }

    def summary(self) -> dict:
        with self._lock:
            return self._summary_unlocked()
