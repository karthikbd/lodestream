"""File share / NFS / SMB mount / local disk source."""
from __future__ import annotations

import mimetypes
import os
from datetime import datetime, timezone
from typing import Iterator, List, Optional

from ..models import DocumentRecord
from ..registry import register_source
from ..utils import to_iso
from .base import Source

ROOT_PARTITION = "(root)"


@register_source("filesystem")
class FilesystemSource(Source):
    """File shares, NFS or SMB mounts, local disks.

        [source]
        type = "filesystem"
        options = { root = "/mnt/share/legal", exclude_hidden = true, follow_symlinks = false }

    Each top-level sub-folder is a partition, scanned in parallel. A changed file (new mtime)
    becomes a new version of the same document.
    """

    def __init__(self, options=None, base_dir="."):
        super().__init__(options, base_dir)
        self.root = os.path.abspath(os.path.join(base_dir, self.options["root"]))
        self.exclude_hidden = self.options.get("exclude_hidden", True)
        self.follow = self.options.get("follow_symlinks", False)

    def partitions(self) -> List[str]:
        parts = [ROOT_PARTITION]
        for e in sorted(os.scandir(self.root), key=lambda e: e.name):
            if e.is_dir(follow_symlinks=self.follow) and not (self.exclude_hidden and e.name.startswith(".")):
                parts.append(e.name)
        return parts

    def _files(self, partition: str):
        if partition == ROOT_PARTITION:
            for e in os.scandir(self.root):
                if e.is_file(follow_symlinks=self.follow):
                    yield e.path
            return
        for dirpath, dirnames, filenames in os.walk(os.path.join(self.root, partition), followlinks=self.follow):
            if self.exclude_hidden:
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for f in filenames:
                yield os.path.join(dirpath, f)

    def iter_documents(self, partition: str, since: Optional[datetime] = None) -> Iterator[DocumentRecord]:
        for path in self._files(partition):
            name = os.path.basename(path)
            if self.exclude_hidden and name.startswith("."):
                continue
            st = os.stat(path)
            mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).replace(tzinfo=None)
            if since and mtime <= since:
                continue
            rel = os.path.relpath(path, self.root).replace(os.sep, "/")
            directory = rel.rsplit("/", 1)[0] if "/" in rel else ""
            yield DocumentRecord(
                source_id=f"{rel}@{st.st_mtime_ns}",
                series_id=rel,
                version_index=0,  # manifest assigns the next version number
                name=name,
                directory=directory,
                size=st.st_size,
                modified=to_iso(mtime),
                content_type=(mimetypes.guess_type(name)[0] or ""),
                source_ref={"path": path},
                partition=partition,
            )

    def open_content(self, record: DocumentRecord):
        return open(record.source_ref["path"], "rb")
