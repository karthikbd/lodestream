"""Source plugin contract. Implement this to migrate from any system."""
from __future__ import annotations

import abc
from datetime import datetime
import itertools
from typing import Any, BinaryIO, Dict, Iterator, List, Optional

from ..checks import CheckContext, CheckResult, run
from ..models import DocumentRecord


class Source(abc.ABC):
    """A system documents are migrated *from*.

    Minimal plugin::

        from lodestream import Source, DocumentRecord, register_source

        @register_source("my_system")
        class MySource(Source):
            def iter_documents(self, partition, since=None):
                for row in my_api.list(partition, modified_after=since):
                    yield DocumentRecord(source_id=f"{row.id}:{row.version}", series_id=row.id,
                                         version_index=row.version, name=row.name,
                                         directory=row.path, size=row.size,
                                         modified=row.modified, source_ref={"id": row.id})

            def open_content(self, record):
                return my_api.download_stream(record.source_ref["id"])
    """

    registered_name = ""

    def __init__(self, options: Optional[Dict[str, Any]] = None, base_dir: str = ".") -> None:
        self.options = options or {}
        self.base_dir = base_dir

    def partitions(self) -> List[str]:
        """Independent slices of the source, scanned in parallel by `inventory`."""
        return [""]

    @abc.abstractmethod
    def iter_documents(self, partition: str, since: Optional[datetime] = None) -> Iterator[DocumentRecord]:
        """Yield metadata for every document version in a partition.
        If ``since`` is given, only versions modified after it (used by `delta`)."""

    @abc.abstractmethod
    def open_content(self, record: DocumentRecord) -> BinaryIO:
        """Return a readable binary stream for the record's content. Caller closes it."""

    def close(self) -> None:
        pass

    # ------------------------------------------------------------------ pre-flight
    def check(self, cc: CheckContext) -> List[CheckResult]:
        """Read-only checks for ``lodestream check``: partitions, sample records, one content read.
        Subclasses add source-specific checks (e.g. SQL schema) and call ``super().check``."""
        results: List[CheckResult] = []
        parts: List[str] = []

        def list_partitions() -> str:
            parts.extend(self.partitions())
            return f"{len(parts)} partition(s): {', '.join(map(str, parts[:5]))}{' ...' if len(parts) > 5 else ''}"

        results.append(run("source", "list partitions", list_partitions))
        if not parts:
            return results
        samples: List[DocumentRecord] = []

        def sample_records() -> Any:
            for part in parts:
                samples.extend(itertools.islice(self.iter_documents(part), cc.sample - len(samples)))
                if len(samples) >= cc.sample:
                    break
            if not samples:
                return "warn", "no documents found in any partition"
            return "; ".join(f"{r.full_path} ({r.size:,} B, v{r.version_index})" for r in samples[:3])

        results.append(run("source", f"read {cc.sample} sample record(s)", sample_records))
        if samples:
            results.append(run("source", "stream one document's content", lambda: self._check_content(samples[0])))
        return results

    def _check_content(self, record: DocumentRecord) -> Any:
        stream = self.open_content(record)
        try:
            total = 0
            while True:
                block = stream.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
        finally:
            stream.close()
        if record.size and total != record.size:
            return "warn", f"{record.full_path}: read {total:,} bytes, metadata says {record.size:,}"
        return f"{record.full_path}: {total:,} bytes"
