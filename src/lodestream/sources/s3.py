"""S3 / S3-compatible object storage source (AWS S3, MinIO, NetApp StorageGRID, Ceph...)."""
from __future__ import annotations

import mimetypes
from datetime import datetime
from typing import Iterator, List, Optional

from ..models import DocumentRecord
from ..registry import register_source
from ..utils import parse_dt, to_iso
from .base import Source


@register_source("s3")
class S3Source(Source):
    """options:
        bucket: legacy-docs
        prefix: archive/                 # optional
        endpoint_url: https://minio:9000 # optional, for S3-compatible stores
        region: us-east-1
        include_versions: false          # true = migrate every object version
        partition_by_prefix: true        # top-level "folders" under prefix are scanned in parallel
    Credentials come from the normal AWS chain (env vars, profile, instance role).
    Object user-metadata (x-amz-meta-*) is NOT fetched at inventory time (one extra call
    per object); add a custom source subclass if you need it."""

    def __init__(self, options=None, base_dir="."):
        super().__init__(options, base_dir)
        import boto3  # optional dependency: pip install lodestream[s3]

        o = self.options
        self.bucket = o["bucket"]
        self.prefix = o.get("prefix", "")
        self.versions = bool(o.get("include_versions", False))
        self.client = boto3.client("s3", endpoint_url=o.get("endpoint_url"), region_name=o.get("region"))

    def partitions(self) -> List[str]:
        if not self.options.get("partition_by_prefix", True):
            return [self.prefix]
        parts = [self.prefix + "\0root"]  # objects directly under prefix
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix, Delimiter="/"):
            parts += [p["Prefix"] for p in page.get("CommonPrefixes", [])]
        return parts

    def _record(self, key: str, size: int, modified, etag: str, version_id=None) -> DocumentRecord:
        rel = key[len(self.prefix):] if key.startswith(self.prefix) else key
        directory, _, name = rel.rpartition("/")
        mod = parse_dt(modified)
        return DocumentRecord(
            source_id=f"{key}@{version_id or etag.strip(chr(34))}",
            series_id=key,
            version_index=int(mod.timestamp()) if (self.versions and mod) else 0,
            name=name, directory=directory, size=int(size), modified=to_iso(mod),
            content_type=mimetypes.guess_type(name)[0] or "",
            source_ref={"key": key, "version_id": version_id},
            partition=directory.split("/")[0] if directory else "(root)",
        )

    def iter_documents(self, partition: str, since: Optional[datetime] = None) -> Iterator[DocumentRecord]:
        root_only = partition.endswith("\0root")
        prefix = partition.replace("\0root", "")
        kwargs = {"Bucket": self.bucket, "Prefix": prefix}
        if root_only:
            kwargs["Delimiter"] = "/"
        if self.versions:
            pages = self.client.get_paginator("list_object_versions").paginate(**kwargs)
            items = ((v, v.get("VersionId")) for p in pages for v in p.get("Versions", []))
        else:
            pages = self.client.get_paginator("list_objects_v2").paginate(**kwargs)
            items = ((o, None) for p in pages for o in p.get("Contents", []))
        for obj, vid in items:
            if obj["Key"].endswith("/"):
                continue
            mod = parse_dt(obj["LastModified"])
            if since and mod and mod <= since:
                continue
            yield self._record(obj["Key"], obj["Size"], obj["LastModified"], obj.get("ETag", ""), vid)

    def open_content(self, record: DocumentRecord):
        kwargs = {"Bucket": self.bucket, "Key": record.source_ref["key"]}
        if record.source_ref.get("version_id"):
            kwargs["VersionId"] = record.source_ref["version_id"]
        return self.client.get_object(**kwargs)["Body"]
