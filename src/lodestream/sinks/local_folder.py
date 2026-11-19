"""Writes documents to a local folder with JSON metadata sidecars.
Use it for dry runs, mapping reviews and throughput tests of the source side."""
from __future__ import annotations

import json
import os
import posixpath
import shutil
from typing import Any, Dict, List, Optional, Tuple

from ..models import DocumentRecord
from ..registry import register_sink
from ..utils import sha256_file, short_hash
from ..checks import CheckContext, CheckResult, run
from .base import LoadItem, LoadResult, Sink


@register_sink("local_folder")
class LocalFolderSink(Sink):
    """Writes documents to a local folder with JSON metadata sidecars, for dry runs, mapping reviews
    and source-side throughput tests.

        [sink]
        type = "local_folder"
        options = { root = "./out", write_metadata = true }
    """

    def __init__(self, options: Optional[Dict[str, Any]] = None, base_dir: str = ".") -> None:
        super().__init__(options, base_dir)
        self.root = os.path.abspath(os.path.join(base_dir, self.options.get("root", "./lodestream-out")))
        self.write_metadata = self.options.get("write_metadata", True)

    def open(self) -> None:
        os.makedirs(self.root, exist_ok=True)

    def _abs(self, rel: str) -> str:
        """The path for a target-relative name, which must stay inside the root folder.

        Folder and file names come from the source system, so they are untrusted: a document called
        ``../../x`` or a folder with a drive or path separator in its name is refused, not written."""
        parts = [p for p in rel.split("/") if p not in ("", ".")]
        for part in parts:
            if part == ".." or os.sep in part or (os.altsep and os.altsep in part) or os.path.splitdrive(part)[0]:
                raise ValueError(f"unsafe path component {part!r} in {rel!r}")
        path = os.path.join(self.root, *parts)
        root = os.path.realpath(self.root)
        if os.path.commonpath([root, os.path.realpath(path)]) != root:
            raise ValueError(f"{rel!r} resolves outside the target folder")
        return path

    def _target(self, item: LoadItem) -> str:
        r = item.record
        if item.previous_target_id:
            return f"{item.previous_target_id.split(';v')[0]};v{r.version_index}"
        folder = (item.folder if item.folder is not None else r.directory).strip("/")
        rel = posixpath.join(folder, r.name) if folder else r.name
        meta = self._abs(rel) + ".meta.json"
        if os.path.exists(meta):
            with open(meta, encoding="utf-8") as fh:
                if json.load(fh).get("series_id") != r.series_id:
                    rel = f"{rel};{short_hash(r.series_id)}"  # different document, same name
        return rel

    def load_batch(self, items: List[LoadItem]) -> List[LoadResult]:
        results = []
        for item in items:
            try:
                rel = self._target(item)
                path = self._abs(rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                tmp = path + ".part"
                with item.open() as src, open(tmp, "wb") as out:
                    shutil.copyfileobj(src, out, 1024 * 1024)
                os.replace(tmp, path)
                if self.write_metadata:
                    with open(path + ".meta.json", "w", encoding="utf-8") as fh:
                        json.dump({"class": item.target_class, "properties": item.properties,
                                   "series_id": item.record.series_id,
                                   "version_index": item.record.version_index,
                                   "previous": item.previous_target_id}, fh, indent=2, default=str)
                results.append(LoadResult(item.record.source_id, target_id=rel))
            except Exception as exc:
                results.append(LoadResult(item.record.source_id, error=f"{type(exc).__name__}: {exc}"))
        return results

    def verify(self, record: DocumentRecord) -> Tuple[bool, str]:
        path = self._abs(record.target_id or "")
        if not record.target_id or not os.path.isfile(path):
            return False, "target file missing"
        size = os.path.getsize(path)
        if record.size and size != record.size:
            return False, f"size {size} != expected {record.size}"
        if record.checksum and sha256_file(path) != record.checksum:
            return False, "checksum mismatch"
        return True, "ok"

    def check(self, cc: CheckContext) -> List[CheckResult]:
        def writable() -> str:
            self.open()
            probe = os.path.join(self.root, ".lodestream-check")
            with open(probe, "w", encoding="utf-8") as fh:
                fh.write("ok")
            os.remove(probe)
            return f"{self.root} is writable"
        return [run("sink", "output folder writable", writable)]
