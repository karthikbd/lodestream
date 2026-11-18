"""End-to-end test against a real SQL Server holding a WSS 3.0-shaped content database.

    docker compose -f tests/e2e/docker-compose.yml up -d      # or point at your own server
    LODESTREAM_E2E=1 pytest tests/e2e -v

The source is read with the *bundled* TDS driver (no pyodbc, no ODBC driver), BLOBs are streamed
in chunks, and documents are uploaded over real HTTP to an in-process FileNet GraphQL stand-in.

Environment (defaults match docker-compose.yml):
    E2E_HOST=127.0.0.1 E2E_PORT=14331 E2E_USER=sa E2E_PASSWORD=Str0ng!Passw0rd E2E_ENCRYPT=optional
"""
import hashlib
import os
import re
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("LODESTREAM_E2E") != "1", reason="set LODESTREAM_E2E=1 to run")

from fakes import FakeFileNet  # noqa: E402
from lodestream import Migration, Status  # noqa: E402
from lodestream.drivers import connect  # noqa: E402

HERE = Path(__file__).parent
E = os.environ.get
SITE = uuid.UUID("11111111-1111-1111-1111-111111111111")
INVOICES = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
CONTRACTS = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000002")
BIG = bytes(range(256)) * (30 * 1024 * 1024 // 256)          # 30 MB, streamed in 4 MB windows
BIG_V1 = b"first draft of the big file" * 1000


def conn_opts(database: str) -> dict:
    return {"host": E("E2E_HOST", "127.0.0.1"), "port": int(E("E2E_PORT", "14331")), "database": database,
            "user": E("E2E_USER", "sa"), "password": E("E2E_PASSWORD", "Str0ng!Passw0rd"),
            "encrypt": E("E2E_ENCRYPT", "optional"), "trust_server_certificate": True,
            "driver": "pytds", "login_timeout": 60}


def run_script(path: Path) -> None:
    c = connect(conn_opts("master"))
    try:
        for batch in re.split(r"^\s*GO\s*$", path.read_text(encoding="utf-8"), flags=re.M | re.I):
            if batch.strip():
                c.cursor().execute(batch)
    finally:
        c.close()


def add_doc(cur, doc_id, list_id, row, dirname, leaf, content, ui_version, title, ctype, modified):
    cur.execute("INSERT INTO AllDocs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1)",
                [doc_id, SITE, dirname, leaf, len(content), modified, ui_version, list_id, row])
    cur.execute("INSERT INTO AllDocStreams VALUES (?, ?, ?)", [doc_id, SITE, content])
    cur.execute("INSERT INTO AllUserData VALUES (?, ?, 1, 0, ?, ?, ?)", [list_id, row, ui_version, title, ctype])


def add_version(cur, doc_id, list_id, row, ui_version, content, title, ctype, created):
    cur.execute("INSERT INTO AllDocVersions VALUES (?, ?, ?, ?, ?, ?)",
                [doc_id, SITE, ui_version, created, len(content), content])
    cur.execute("INSERT INTO AllUserData VALUES (?, ?, 0, 0, ?, ?, ?)", [list_id, row, ui_version, title, ctype])


@pytest.fixture(scope="module")
def wss_db():
    run_script(HERE / "seed_wss.sql")
    c = connect(conn_opts("WSS_Content_E2E"))
    cur = c.cursor()
    cur.execute("INSERT INTO AllLists VALUES (?, N'Invoices'), (?, N'Contracts')", [INVOICES, CONTRACTS])
    ids = {k: uuid.uuid4() for k in ("big", "inv", "msa", "form")}
    old = "2024-03-01 10:00:00"
    add_doc(cur, ids["big"], INVOICES, 1, "sites/fin/Invoices", "scan-archive.pdf", BIG, 1024,
            "Scanned archive", "Invoice", old)
    add_version(cur, ids["big"], INVOICES, 1, 512, BIG_V1, "Scanned archive (draft)", "Invoice", "2024-01-01 09:00:00")
    add_doc(cur, ids["inv"], INVOICES, 2, "sites/fin/Invoices/2019", "inv-002.pdf", b"INVOICE-2" * 30, 512,
            "Invoice 2", "Invoice", old)
    add_doc(cur, ids["msa"], CONTRACTS, 1, "sites/fin/Contracts", "msa.docx", "Ünïcödé contract".encode() * 99, 512,
            "Master agreement", "Contract", old)
    add_doc(cur, ids["form"], CONTRACTS, 2, "sites/fin/Contracts/Forms", "AllItems.aspx", b"<html/>", 512,
            None, "Document", old)
    c.close()
    return ids


def config(tmp_path, endpoint):
    return {
        "manifest": "state/manifest.db",
        "source": {"type": "wss_sql", "options": {
            **conn_opts("WSS_Content_E2E"), "chunk_size_mb": 4,
            "userdata_columns": {"nvarchar1": "Title", "tp_ContentType": "ContentType"},
            "content_type_field": "ContentType"}},
        "sink": {"type": "filenet_graphql", "options": {"endpoint": endpoint, "repository": "OS1",
                                                        "auth": {"type": "basic", "username": "u", "password": "p"}}},
        "mapping": {"classes": {"Invoice": "Invoice", "Contract": "Contract"},
                    "properties": {"Title": "DocumentTitle", "_source_id": "MigrationSourceId",
                                   "_version_label": "SourceVersion"},
                    "folder": "/Migrated/{directory}", "strip_path_prefixes": ["sites/fin"]},
        "steps": [{"inventory": {"workers": 2}}, {"filter": {"exclude_patterns": ["*/forms/*"]}},
                  {"extract": {"staging_dir": "staging", "workers": 2}}, {"load": {"workers": 2, "batch_size": 2}},
                  {"verify": {"workers": 2, "report": "state/report.json"}}],
        "rolling": {"chunk_docs": 2},
    }


def counts(cfg, base):
    return {k: v[0] for k, v in Migration(cfg, base).manifest.counts().items()}


def test_wss_to_filenet_bundled_driver(wss_db, tmp_path):
    with FakeFileNet() as fn:
        cfg = config(tmp_path, fn.endpoint)
        Migration(cfg, str(tmp_path)).run()
        assert counts(cfg, str(tmp_path)) == {"VERIFIED": 4, "SKIPPED": 1}   # 2 versions + 2 docs; Forms page skipped

        uploaded = [b for u in fn.uploads for b in u["files"].values()]
        assert hashlib.sha256(BIG).digest() in {hashlib.sha256(b).digest() for b in uploaded}, "30 MB BLOB intact"
        assert BIG_V1 in uploaded
        assert "Ünïcödé contract".encode() * 99 in uploaded
        create_q = "\n".join(u["query"] for u in fn.uploads)
        assert 'classIdentifier: "Invoice"' in create_q and 'classIdentifier: "Contract"' in create_q
        assert 'fileInFolderIdentifier: "/Migrated/Invoices/2019"' in create_q
        assert '{SourceVersion: "1.0"}' in create_q
        assert any(r["chunked"] for r in fn.requests), "uploads are streamed with chunked encoding"
        assert any("checkinDocument" in u["query"] and '{SourceVersion: "2.0"}' in u["query"] for u in fn.uploads)

        # ---- delta: the big file is edited in SharePoint after the bulk run --------------------------
        c = connect(conn_opts("WSS_Content_E2E"))
        cur = c.cursor()
        doc = wss_db["big"]
        new = b"edited after the bulk load" * 5000
        cur.execute("INSERT INTO AllDocVersions SELECT d.Id, d.SiteId, d.UIVersion, d.TimeLastModified, d.Size, s.Content "
                    "FROM AllDocs d JOIN AllDocStreams s ON s.Id = d.Id AND s.SiteId = d.SiteId WHERE d.Id = ?", [doc])
        cur.execute("UPDATE AllDocs SET UIVersion = 1536, Size = ?, TimeLastModified = GETUTCDATE() WHERE Id = ?",
                    [len(new), doc])
        cur.execute("UPDATE AllDocStreams SET Content = ? WHERE Id = ?", [new, doc])
        cur.execute("UPDATE AllUserData SET tp_IsCurrentVersion = 0 WHERE tp_ListId = ? AND tp_ID = 1", [INVOICES])
        cur.execute("INSERT INTO AllUserData VALUES (?, 1, 1, 0, 1536, N'Scanned archive', N'Invoice')", [INVOICES])
        c.close()

        before = len(fn.uploads)
        Migration(cfg, str(tmp_path)).run(steps=["delta", "filter", "extract", "load", "verify"])
        assert counts(cfg, str(tmp_path)) == {"VERIFIED": 5, "SKIPPED": 1}
        delta_uploads = fn.uploads[before:]
        assert len(delta_uploads) == 1 and "checkinDocument" in delta_uploads[0]["query"]
        assert new in delta_uploads[0]["files"].values()
        m = Migration(cfg, str(tmp_path))
        latest = m.manifest.get(f"{doc}:1536")
        assert latest.status == Status.VERIFIED and latest.properties["_version_label"] == "3.0"
