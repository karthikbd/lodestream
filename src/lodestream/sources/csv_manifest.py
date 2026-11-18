"""Universal fallback source: a CSV listing (exported from ANY system) plus the
files themselves on a share. If a legacy system can export "file path + metadata",
it can be migrated with this source."""
from __future__ import annotations

import csv
import glob
import os
from datetime import datetime
from typing import Iterator, List, Optional

from ..models import DocumentRecord
from ..registry import register_source
from ..utils import require_dt, to_iso
from .base import Source

_DEFAULT_COLUMNS = {
    "id": "id", "version": "version", "name": "name", "directory": "directory",
    "file": "file", "size": "size", "modified": "modified", "content_type": "content_type",
}


@register_source("csv_manifest")
class CsvManifestSource(Source):
    """A CSV listing exported from any system, plus the files on a share.

        [source]
        type = "csv_manifest"

        [source.options]
        path = "exports/*.csv"              # glob; each CSV file is a partition (parallel scan)
        content_root = "/mnt/export/files"  # relative `file` paths are resolved against this
        delimiter = ","
        encoding = "utf-8-sig"

        [source.options.columns]            # your CSV header -> lodestream field
        id = "DocumentId"
        version = "VersionNo"
        name = "FileName"
        directory = "FolderPath"
        file = "StoragePath"
        modified = "LastModified"
        content_type = "DocType"

    Every other column becomes a metadata property.
    """

    def __init__(self, options=None, base_dir="."):
        super().__init__(options, base_dir)
        self.pattern = os.path.join(base_dir, self.options["path"])
        self.content_root = os.path.join(base_dir, self.options.get("content_root", "."))
        self.columns = {**_DEFAULT_COLUMNS, **(self.options.get("columns") or {})}
        self.delimiter = self.options.get("delimiter", ",")
        self.encoding = self.options.get("encoding", "utf-8-sig")

    def partitions(self) -> List[str]:
        files = sorted(glob.glob(self.pattern))
        if not files:
            raise FileNotFoundError(f"No CSV files match {self.pattern}")
        return files

    def iter_documents(self, partition: str, since: Optional[datetime] = None) -> Iterator[DocumentRecord]:
        c = self.columns
        used = set(c.values())
        with open(partition, newline="", encoding=self.encoding) as fh:
            for row in csv.DictReader(fh, delimiter=self.delimiter):
                file_path = row.get(c["file"]) or ""
                if not file_path:
                    continue
                path = file_path if os.path.isabs(file_path) else os.path.join(self.content_root, file_path)
                name = row.get(c["name"]) or os.path.basename(file_path)
                doc_id = row.get(c["id"]) or file_path
                version = row.get(c["version"])
                modified = row.get(c["modified"]) or ""
                if since and modified and require_dt(modified) <= since:
                    continue
                size = row.get(c["size"])
                yield DocumentRecord(
                    source_id=f"{doc_id}:{version}" if version else doc_id,
                    series_id=doc_id,
                    version_index=int(float(version)) if version else 0,
                    name=name,
                    directory=row.get(c["directory"]) or "",
                    size=int(float(size)) if size else 0,
                    modified=to_iso(modified) if modified else "",
                    content_type=row.get(c["content_type"]) or "",
                    properties={k: v for k, v in row.items() if k not in used and k and v not in (None, "")},
                    source_ref={"path": path},
                    partition=os.path.basename(partition),
                )

    def open_content(self, record: DocumentRecord):
        return open(record.source_ref["path"], "rb")
