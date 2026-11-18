"""Core data model shared by sources, sinks and stages."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class Status(str, enum.Enum):
    PENDING = "PENDING"        # registered by inventory, nothing done yet
    SKIPPED = "SKIPPED"        # excluded by the filter step
    EXTRACTED = "EXTRACTED"    # content copied to staging + checksummed
    LOADED = "LOADED"          # created in the target repository
    VERIFIED = "VERIFIED"      # target checked against the manifest
    FAILED = "FAILED"          # extract or load failed (retryable)
    MISMATCH = "MISMATCH"      # loaded but verification failed (needs a human)


@dataclass
class DocumentRecord:
    """One version of one document.

    ``series_id`` groups all versions of the same logical document;
    ``version_index`` orders them (higher = newer). A source may leave
    ``version_index`` at 0 and the manifest assigns the next number.
    """

    source_id: str
    series_id: str
    version_index: int = 0
    name: str = ""
    directory: str = ""
    size: int = 0
    modified: str = ""
    content_type: str = ""
    properties: Dict[str, Any] = field(default_factory=dict)
    source_ref: Dict[str, Any] = field(default_factory=dict)
    partition: str = ""
    status: Status = Status.PENDING
    checksum: Optional[str] = None
    staged_path: Optional[str] = None
    target_id: Optional[str] = None
    error: Optional[str] = None
    attempts: int = 0

    @property
    def full_path(self) -> str:
        d = (self.directory or "").strip("/")
        return f"/{d}/{self.name}" if d else f"/{self.name}"

    def builtin_fields(self) -> Dict[str, Any]:
        """Fields usable as mapping sources (prefixed with an underscore)."""
        return {
            "_name": self.name,
            "_directory": self.directory,
            "_path": self.full_path,
            "_size": self.size,
            "_modified": self.modified,
            "_content_type": self.content_type,
            "_source_id": self.source_id,
            "_series_id": self.series_id,
            "_version_index": self.version_index,
            "_partition": self.partition,
        }
