"""Windows SharePoint Services (WSS 3.0 / MOSS 2007) preset of the sql_blob source.

Reads directly from a *restored copy* of the WSS content database: never point
this at the live production database (unsupported by Microsoft and it would
hurt users). Defaults target the WSS 3.0 schema (AllDocs, AllDocStreams,
AllDocVersions, AllUserData, AllLists). Schemas vary by version and patch level,
so run `lodestream inventory` on a small list first and override any query in
the config if needed.
"""
from __future__ import annotations

import re

from ..models import DocumentRecord
from ..registry import register_source
from .sql_blob import SqlBlobSource

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_CURRENT = """SELECT d.Id AS id, d.UIVersion AS version, d.LeafName AS name, d.DirName AS directory,
       d.Size AS size, d.TimeLastModified AS modified, l.tp_Title AS content_type,
       d.ListId AS partition, d.SiteId AS ref_site, 'current' AS ref_kind{userdata}
FROM AllDocs d
LEFT JOIN AllLists l ON l.tp_ID = d.ListId
LEFT JOIN AllUserData u ON u.tp_ListId = d.ListId AND u.tp_ID = d.DoclibRowId
                       AND u.tp_IsCurrentVersion = 1 AND u.tp_RowOrdinal = 0
WHERE d.Type = 0 AND d.IsCurrentVersion = 1 AND d.ListId = ?{since_filter}"""

_VERSIONS = """SELECT v.Id AS id, v.UIVersion AS version, d.LeafName AS name, d.DirName AS directory,
       v.Size AS size, v.TimeCreated AS modified, l.tp_Title AS content_type,
       d.ListId AS partition, v.SiteId AS ref_site, 'version' AS ref_kind{userdata}
FROM AllDocVersions v
JOIN AllDocs d ON d.Id = v.Id AND d.SiteId = v.SiteId AND d.IsCurrentVersion = 1
LEFT JOIN AllLists l ON l.tp_ID = d.ListId
LEFT JOIN AllUserData u ON u.tp_ListId = d.ListId AND u.tp_ID = d.DoclibRowId
                       AND u.tp_UIVersion = v.UIVersion AND u.tp_RowOrdinal = 0
WHERE d.Type = 0 AND d.ListId = ?{since_filter}"""


@register_source("wss_sql")
class WssSqlSource(SqlBlobSource):
    """options (in addition to sql_blob connection options):
        include_versions: true          # migrate version history (AllDocVersions)
        userdata_columns:               # AllUserData column -> property name
          nvarchar1: Title
          datetime1: InvoiceDate
          tp_ContentType: ContentType
        site_ids: [..]                  # optional: restrict to these site collections
        list_ids: [..]                  # optional: restrict to these document libraries
    Partitions = document libraries (ListId); content_type = library title."""

    def __init__(self, options=None, base_dir="."):
        options = dict(options or {})
        ud_cols = options.get("userdata_columns") or {}
        for col, alias in ud_cols.items():
            if not (_IDENT.match(col) and _IDENT.match(alias)):
                raise ValueError(f"Invalid userdata column mapping {col!r}: {alias!r}")
        ud = "".join(f", u.{c} AS {a}" for c, a in ud_cols.items())

        where, params = "", []
        if options.get("site_ids"):
            where += f" AND d.SiteId IN ({','.join('?' for _ in options['site_ids'])})"
            params += list(options["site_ids"])
        if options.get("list_ids"):
            where += f" AND d.ListId IN ({','.join('?' for _ in options['list_ids'])})"
            params += list(options["list_ids"])

        queries = [{"sql": _CURRENT.replace("{userdata}", ud), "since_column": "d.TimeLastModified"}]
        if options.get("include_versions", True):
            queries.append({"sql": _VERSIONS.replace("{userdata}", ud), "since_column": "v.TimeCreated"})

        options.setdefault("dialect", "mssql")
        options.setdefault("partitions_query",
                           "SELECT DISTINCT d.ListId FROM AllDocs d WHERE d.Type = 0 "
                           "AND d.ListId IS NOT NULL" + where)
        options.setdefault("partitions_params", params)
        options.setdefault("documents_queries", queries)
        options.setdefault("content", {
            "current": {
                "length_query": "SELECT {length}(Content) FROM AllDocStreams WHERE Id = ? AND SiteId = ?",
                "chunk_query": "SELECT {substr}(Content, ?, ?) FROM AllDocStreams WHERE Id = ? AND SiteId = ?",
                "params": ["id", "ref_site"],
            },
            "version": {
                "length_query": "SELECT {length}(Content) FROM AllDocVersions "
                                "WHERE Id = ? AND SiteId = ? AND UIVersion = ?",
                "chunk_query": "SELECT {substr}(Content, ?, ?) FROM AllDocVersions "
                               "WHERE Id = ? AND SiteId = ? AND UIVersion = ?",
                "params": ["id", "ref_site", "version"],
            },
        })
        self.content_type_field = options.get("content_type_field")  # e.g. ContentType alias
        super().__init__(options, base_dir)

    def postprocess(self, record: DocumentRecord) -> DocumentRecord:
        major, minor = divmod(int(record.version_index or 512), 512)
        record.properties["_version_label"] = f"{major}.{minor}"
        if self.content_type_field and record.properties.get(self.content_type_field):
            record.content_type = str(record.properties[self.content_type_field])
        return record
