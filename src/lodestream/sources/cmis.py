"""CMIS 1.1 Browser Binding source: Alfresco, Documentum (CMIS), OpenText,
Nuxeo, SharePoint 2013+ on-prem CMIS producer, and other CMIS-compliant ECMs."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

from .._http import HttpClient, HttpError
from ..models import DocumentRecord
from ..registry import register_source
from ..utils import jsonable, to_iso
from .base import Source


def _ms_to_dt(value) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).replace(tzinfo=None)
    from ..utils import parse_dt
    return parse_dt(value)


@register_source("cmis")
class CmisSource(Source):
    """CMIS 1.1 browser-binding repositories. Uses only the Python standard library (urllib) and
    talks only to ``url``.

        [source]
        type = "cmis"

        [source.options]
        url = "https://host/alfresco/api/-default-/public/cmis/versions/1.1/browser"
        repository_id = "-default-"         # optional; first repository if omitted
        username = "${CMIS_USER}"
        password = "${CMIS_PASSWORD}"
        folders = ["/Sites/finance/documentLibrary", "/Shared"]   # each is a partition
        include_versions = false
        page_size = 500
        verify_tls = true

    content_type = cmis:objectTypeId (map it to a class in [mapping.classes]); non-cmis:* properties
    (custom metadata) become properties.
    """

    def __init__(self, options=None, base_dir="."):
        super().__init__(options, base_dir)
        o = self.options
        auth = {"type": "basic", "username": o["username"], "password": o.get("password", "")} \
            if o.get("username") else None
        self.client = HttpClient(auth=auth, verify=o.get("verify_tls", True), timeout=o.get("timeout", 600))
        self.page_size = int(o.get("page_size", 500))
        self.include_versions = bool(o.get("include_versions", False))
        info = self._get(o["url"])
        repo_id = o.get("repository_id") or next(iter(info))
        self.root_url = info[repo_id]["rootFolderUrl"]

    def _get(self, url: str, **params) -> Any:
        resp = self.client.get(url, params=params)
        if resp.status >= 400:
            raise HttpError(resp.status, resp.text)
        return resp.json()

    def partitions(self) -> List[str]:
        return list(self.options.get("folders") or ["/"])

    def _children(self, folder_id: str) -> Iterator[Dict[str, Any]]:
        skip = 0
        while True:
            data = self._get(self.root_url, objectId=folder_id, cmisselector="children",
                             succinct="true", maxItems=self.page_size, skipCount=skip)
            objs = data.get("objects", [])
            for o in objs:
                yield o["object"]["succinctProperties"]
            if not data.get("hasMoreItems") or not objs:
                return
            skip += len(objs)

    def _record(self, p: Dict[str, Any], directory: str, partition: str, vindex: int) -> DocumentRecord:
        mod = _ms_to_dt(p.get("cmis:lastModificationDate"))
        props = {k: jsonable(v[0] if isinstance(v, list) and len(v) == 1 else v)
                 for k, v in p.items() if not k.startswith("cmis:") and v not in (None, [], "")}
        props["_version_label"] = p.get("cmis:versionLabel")
        props["_created_by"] = p.get("cmis:createdBy")
        return DocumentRecord(
            source_id=p["cmis:objectId"],
            series_id=p.get("cmis:versionSeriesId") or p["cmis:objectId"],
            version_index=vindex,
            name=p.get("cmis:name", ""),
            directory=directory,
            size=int(p.get("cmis:contentStreamLength") or 0),
            modified=to_iso(mod),
            content_type=p.get("cmis:objectTypeId", ""),
            properties=props,
            source_ref={"object_id": p["cmis:objectId"]},
            partition=partition,
        )

    def iter_documents(self, partition: str, since: Optional[datetime] = None) -> Iterator[DocumentRecord]:
        root = self._get(self.root_url.rstrip("/") + "/" + partition.strip("/"),
                         cmisselector="object", succinct="true") if partition.strip("/") else \
            self._get(self.root_url, cmisselector="object", succinct="true")
        stack = [(root["succinctProperties"]["cmis:objectId"], partition.strip("/"))]
        while stack:
            fid, path = stack.pop()
            for p in self._children(fid):
                base = p.get("cmis:baseTypeId")
                if base == "cmis:folder":
                    stack.append((p["cmis:objectId"], f"{path}/{p['cmis:name']}".strip("/")))
                elif base == "cmis:document" and p.get("cmis:contentStreamLength"):
                    versions = [p]
                    if self.include_versions:
                        data = self._get(self.root_url, objectId=p["cmis:objectId"],
                                         cmisselector="versions", succinct="true")
                        versions = [v["succinctProperties"] for v in (data or [])] or [p]
                    total = len(versions)
                    for i, v in enumerate(versions):  # CMIS returns newest first
                        mod = _ms_to_dt(v.get("cmis:lastModificationDate"))
                        if since and mod and mod <= since:
                            continue
                        yield self._record(v, path, partition, total - i)

    def open_content(self, record: DocumentRecord):
        return self.client.open_stream(self.root_url, params={"objectId": record.source_ref["object_id"],
                                                              "cmisselector": "content"})
