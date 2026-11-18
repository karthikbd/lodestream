"""Generic source for any relational database that stores file content as BLOBs
(SharePoint/WSS content DBs, home-grown DMS tables, legacy imaging systems...).

You supply SQL; lodestream handles partitioning, delta filtering and chunked
streaming of large BLOBs (so a 2 GB file is never loaded into memory at once).

Column conventions for document queries (use SQL aliases):
    id            required  unique key of the logical document (version series)
    version       optional  integer, higher = newer
    name          required  file name
    directory     optional  folder path
    size          optional  bytes
    modified      optional  last-modified timestamp
    content_type  optional  used to choose the target document class
    partition     optional
    ref_*         optional  extra values needed to fetch content (kept in source_ref)
    anything else -> becomes a metadata property (mapped in the `mapping` section)
"""
from __future__ import annotations

import io
import threading
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

from ..models import DocumentRecord
from ..registry import register_source
from ..drivers import connect
from ..utils import jsonable, require_dt, to_iso
from .base import Source

DIALECTS = {
    "mssql": {"substr": "SUBSTRING", "length": "DATALENGTH"},
    "sqlite": {"substr": "substr", "length": "length"},
    "postgres": {"substr": "substring", "length": "octet_length"},
    "oracle": {"substr": "dbms_lob.substr", "length": "dbms_lob.getlength"},
}
_STANDARD = {"id", "version", "name", "directory", "size", "modified", "content_type", "partition"}


class SqlBlobReader(io.RawIOBase):
    """Streams a BLOB in fixed-size windows: SELECT SUBSTRING(col, start, len) ..."""

    def __init__(self, conn, chunk_sql: str, params: List[Any], length: int, chunk_size: int):
        self._conn, self._sql, self._params = conn, chunk_sql, params
        self._length, self._chunk = length, chunk_size
        self._pos, self._buf, self._off = 0, b"", 0

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        if self._off >= len(self._buf):
            if self._pos >= self._length:
                return 0
            n = min(self._chunk, self._length - self._pos)
            cur = self._conn.cursor()
            cur.execute(self._sql, [self._pos + 1, n, *self._params])
            row = cur.fetchone()
            data = bytes(row[0]) if row and row[0] is not None else b""
            if not data:
                raise IOError(f"BLOB ended early at byte {self._pos} of {self._length}")
            self._buf, self._off = data, 0
        take = min(len(b), len(self._buf) - self._off)
        b[:take] = self._buf[self._off:self._off + take]
        self._off += take
        self._pos += take
        return take


@register_source("sql_blob")
class SqlBlobSource(Source):
    """Any database that stores file content as BLOBs. SQL Server is reached with the bundled driver
    (or pyodbc, if already installed); other databases through ``connection_factory``.

        [source]
        type = "sql_blob"

        [source.options]
        driver = "auto"                     # auto | pytds | pyodbc | sqlite3 | factory
        host = "legacydb"                   # SQL Server: host, port, instance, database, user
        port = 1433
        database = "DMS"
        user = "dms_reader"
        password_env = "DMS_DB_PASSWORD"    # or password_file (wins, e.g. a Secret mount) or password
        encrypt = "optional"                # off | optional | required
        trust_server_certificate = false    # also: ca_file, hostname_in_certificate, login_timeout, query_timeout
        # connection_string / odbc_driver   (pyodbc only)
        # connection_factory = "mypkg.db:connect"   (any other DB-API database)
        dialect = "mssql"                   # mssql | sqlite | postgres | oracle ({substr}/{length} tokens)
        paramstyle = "qmark"                # format = %s placeholders (e.g. psycopg2)
        partitions_query = "SELECT DISTINCT CabinetId FROM Documents"   # optional
        chunk_size_mb = 8

        [[source.options.documents_queries]]   # each gets the partition as its first ? parameter
        sql = "SELECT DocId AS id, Ver AS version, FileName AS name ... WHERE CabinetId = ? {since_filter}"
        since_column = "d.Modified"

        [source.options.content.default]     # chunk params are (start, length, *params)
        length_query = "SELECT {length}(Data) FROM Blobs WHERE DocId = ? AND Ver = ?"
        chunk_query = "SELECT {substr}(Data, ?, ?) FROM Blobs WHERE DocId = ? AND Ver = ?"
        params = ["id", "version"]
        # or, for small files only:  blob_query = "SELECT Data FROM Blobs WHERE DocId = ?"

    Result columns: id (required), version, name, directory, size, modified, content_type, partition;
    ref_* columns are kept to fetch content (ref_kind picks a [content.<kind>] entry); every other
    column becomes a metadata property.
    """

    default_options: Dict[str, Any] = {}

    def __init__(self, options=None, base_dir="."):
        merged = {**self.default_options, **(options or {})}
        super().__init__(merged, base_dir)
        o = self.options
        self.dialect = o.get("dialect", "mssql")
        self.tokens = DIALECTS.get(self.dialect, DIALECTS["mssql"])
        self.paramstyle = o.get("paramstyle", "format" if self.dialect == "postgres" else "qmark")
        self.chunk_size = int(float(o.get("chunk_size_mb", 8)) * 1024 * 1024)
        self.fetch_size = int(o.get("fetch_size", 5000))
        self._local = threading.local()
        self._all_conns: List[Any] = []
        self._lock = threading.Lock()
        queries = o.get("documents_queries") or o.get("documents_query")
        if not queries:
            raise ValueError("sql_blob source needs documents_queries")
        if isinstance(queries, (str, dict)):
            queries = [queries]
        self.doc_queries = [q if isinstance(q, dict) else {"sql": q} for q in queries]
        self.content = o.get("content") or {}

    # -------------------------------------------------------------- connections
    def _connect(self):
        return connect(self.options, self.base_dir)

    def _conn(self):
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            self._local.conn = conn
            with self._lock:
                self._all_conns.append(conn)
        return conn

    def close(self) -> None:
        with self._lock:
            for c in self._all_conns:
                try:
                    c.close()
                except Exception:  # pragma: no cover
                    pass
            self._all_conns.clear()
        self._local = threading.local()

    def _sql(self, sql: str, since_column: Optional[str] = None, since: Optional[datetime] = None) -> str:
        sql = sql.replace("{substr}", self.tokens["substr"]).replace("{length}", self.tokens["length"])
        sql = sql.replace("{since_filter}", f" AND {since_column} > ?" if since and since_column else "")
        if self.paramstyle == "format":
            sql = sql.replace("?", "%s")
        return sql

    def _since_param(self, since: datetime):
        return since.strftime("%Y-%m-%dT%H:%M:%S") if self.dialect == "sqlite" else since

    # -------------------------------------------------------------- inventory
    def partitions(self) -> List[str]:
        q = self.options.get("partitions_query")
        if not q:
            return [""]
        cur = self._conn().cursor()
        cur.execute(self._sql(q), list(self.options.get("partitions_params", [])))
        return [str(r[0]) for r in cur.fetchall() if r[0] is not None]

    def _row_to_record(self, row: Dict[str, Any], partition: str) -> DocumentRecord:
        lower = {k.lower(): v for k, v in row.items()}
        doc_id = str(lower["id"])
        version = lower.get("version")
        ref = {k: jsonable(v) for k, v in row.items() if k.lower().startswith("ref_")}
        ref.update(id=doc_id, version=jsonable(version))
        props = {k: jsonable(v) for k, v in row.items()
                 if k.lower() not in _STANDARD and not k.lower().startswith("ref_") and v is not None}
        part = lower.get("partition")
        return DocumentRecord(
            source_id=f"{doc_id}:{version}" if version is not None else doc_id,
            series_id=doc_id,
            version_index=int(version) if version is not None else 0,
            name=str(lower.get("name") or doc_id),
            directory=str(lower.get("directory") or ""),
            size=int(lower.get("size") or 0),
            modified=to_iso(lower.get("modified")),
            content_type=str(lower.get("content_type") or ""),
            properties=props,
            source_ref=ref,
            partition=str(part) if part is not None else partition,
        )

    def postprocess(self, record: DocumentRecord) -> DocumentRecord:
        """Hook for presets (e.g. WSS version labels)."""
        return record

    def iter_documents(self, partition: str, since: Optional[datetime] = None) -> Iterator[DocumentRecord]:
        cur = self._conn().cursor()
        for q in self.doc_queries:
            since_col = q.get("since_column")
            sql = self._sql(q["sql"], since_col, since)
            params: List[Any] = [partition] if self.options.get("partitions_query") else []
            if since and since_col and "{since_filter}" in q["sql"]:
                params.append(self._since_param(since))
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            while True:
                rows = cur.fetchmany(self.fetch_size)
                if not rows:
                    break
                for raw in rows:
                    rec = self.postprocess(self._row_to_record(dict(zip(cols, raw, strict=False)), partition))
                    if since and rec.modified and require_dt(rec.modified) <= since:
                        continue
                    yield rec

    # -------------------------------------------------------------- content
    def open_content(self, record: DocumentRecord):
        ref = record.source_ref
        spec = self.content.get(ref.get("ref_kind") or "default") or self.content.get("default")
        if not spec:
            raise ValueError(f"No content query configured for kind {ref.get('ref_kind')!r}")
        params = [ref.get(p) for p in spec.get("params", ["id"])]
        conn = self._conn()
        if spec.get("blob_query"):
            cur = conn.cursor()
            cur.execute(self._sql(spec["blob_query"]), params)
            row = cur.fetchone()
            if not row or row[0] is None:
                raise FileNotFoundError(f"No content for {record.source_id}")
            return io.BytesIO(bytes(row[0]))
        cur = conn.cursor()
        cur.execute(self._sql(spec["length_query"]), params)
        row = cur.fetchone()
        if not row or row[0] is None:
            raise FileNotFoundError(f"No content for {record.source_id}")
        reader = SqlBlobReader(conn, self._sql(spec["chunk_query"]), params, int(row[0]), self.chunk_size)
        return io.BufferedReader(reader, buffer_size=self.chunk_size)
