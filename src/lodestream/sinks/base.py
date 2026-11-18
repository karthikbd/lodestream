"""Sink plugin contract: where documents are migrated *to*."""
from __future__ import annotations

import abc
import mimetypes
from dataclasses import dataclass, field
from typing import Any, BinaryIO, Callable, Dict, List, Optional, Tuple

from ..models import DocumentRecord
from ..utils import HashingReader


@dataclass
class LoadItem:
    record: DocumentRecord
    target_class: str
    properties: Dict[str, Any]
    folder: Optional[str]
    previous_target_id: Optional[str]          # set => add a new version to this document
    opener: Callable[[], BinaryIO]
    reader: Optional[HashingReader] = field(default=None, repr=False)

    def open(self) -> HashingReader:
        self.reader = HashingReader(self.opener())
        return self.reader

    def close(self) -> None:
        if self.reader:
            self.reader.close()

    @property
    def mime(self) -> str:
        return mimetypes.guess_type(self.record.name)[0] or "application/octet-stream"


@dataclass
class LoadResult:
    source_id: str
    target_id: Optional[str] = None
    error: Optional[str] = None


class Sink(abc.ABC):
    registered_name = ""

    def __init__(self, options: Optional[Dict[str, Any]] = None, base_dir: str = "."):
        self.options = options or {}
        self.base_dir = base_dir

    def open(self) -> None:
        """Connect / authenticate. Called once before the first load or verify."""

    @abc.abstractmethod
    def load_batch(self, items: List[LoadItem]) -> List[LoadResult]:
        """Create documents (or new versions). Must return one result per item and
        must call ``item.open()`` to read content (that is how checksums are computed)."""

    @abc.abstractmethod
    def verify(self, record: DocumentRecord) -> Tuple[bool, str]:
        """Check the loaded document exists and matches. Returns (ok, message)."""

    def close(self) -> None:
        pass
