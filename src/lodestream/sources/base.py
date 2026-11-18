"""Source plugin contract. Implement this to migrate from any system."""
from __future__ import annotations

import abc
from datetime import datetime
from typing import Any, BinaryIO, Dict, Iterator, List, Optional

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

    def __init__(self, options: Optional[Dict[str, Any]] = None, base_dir: str = "."):
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
