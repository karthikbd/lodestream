import json
import os
import sqlite3

import pytest

from lodestream import LoadResult, Migration, Status, register_sink
from lodestream.cli import main as cli_main

from fakes import FakeCmis, FakeFileNet
from lodestream.sinks.local_folder import LocalFolderSink

LIST_A, LIST_B = "list-aaaa", "list-bbbb"
SITE = "site-1"


# --------------------------------------------------------------------- fake WSS
def make_wss_db(path):
    """A tiny WSS 3.0-shaped content database in SQLite."""
    c = sqlite3.connect(path)
    c.executescript("""
    CREATE TABLE AllLists (tp_ID TEXT, tp_Title TEXT);
    CREATE TABLE AllDocs (Id TEXT, SiteId TEXT, DirName TEXT, LeafName TEXT, Size INT,
        TimeLastModified TEXT, UIVersion INT, ListId TEXT, DoclibRowId INT, Type INT, IsCurrentVersion INT);
    CREATE TABLE AllDocStreams (Id TEXT, SiteId TEXT, Content BLOB);
    CREATE TABLE AllDocVersions (Id TEXT, SiteId TEXT, UIVersion INT, TimeCreated TEXT, Size INT, Content BLOB);
    CREATE TABLE AllUserData (tp_ListId TEXT, tp_ID INT, tp_IsCurrentVersion INT, tp_RowOrdinal INT,
        tp_UIVersion INT, nvarchar1 TEXT, tp_ContentType TEXT);
    """)
    c.execute("INSERT INTO AllLists VALUES (?, 'Invoices'), (?, 'Contracts')", (LIST_A, LIST_B))
    docs = [
        # id, dir, leaf, list, row, content(current), versions [(uiv, content)], ctype
        ("doc1", "sites/fin/Invoices", "inv-001.pdf", LIST_A, 1, b"INVOICE-1-v3" * 50,
         [(512, b"INVOICE-1-v1" * 40), (1024, b"INVOICE-1-v2" * 45)], "Invoice"),
        ("doc2", "sites/fin/Invoices/2019", "inv-002.pdf", LIST_A, 2, b"INVOICE-2" * 30, [], "Invoice"),
        ("doc3", "sites/fin/Contracts", "msa.docx", LIST_B, 1, b"CONTRACT" * 99, [(512, b"C-OLD" * 10)], "Contract"),
        ("doc4", "sites/fin/Contracts/Forms", "AllItems.aspx", LIST_B, 2, b"<html/>", [], "Document"),
    ]
    for (i, d, leaf, lst, row, content, versions, ctype) in docs:
        cur_ver = (max([v for v, _ in versions]) + 512) if versions else 512
        c.execute("INSERT INTO AllDocs VALUES (?,?,?,?,?,?,?,?,?,0,1)",
                  (i, SITE, d, leaf, len(content), "2024-03-01T10:00:00", cur_ver, lst, row))
        c.execute("INSERT INTO AllDocStreams VALUES (?,?,?)", (i, SITE, content))
        c.execute("INSERT INTO AllUserData VALUES (?,?,1,0,?,?,?)", (lst, row, cur_ver, f"Title {leaf}", ctype))
        for uiv, vc in versions:
            c.execute("INSERT INTO AllDocVersions VALUES (?,?,?,?,?,?)",
                      (i, SITE, uiv, f"2023-0{uiv // 512}-01T09:00:00", len(vc), vc))
            c.execute("INSERT INTO AllUserData VALUES (?,?,0,0,?,?,?)", (lst, row, uiv, f"Old {leaf}", ctype))
    c.commit()
    c.close()


def wss_config(tmp_path, steps, **extra):
    cfg = {
        "manifest": "state/manifest.db",
        "source": {"type": "wss_sql", "options": {
            "driver": "sqlite3", "database": "wss.db", "dialect": "sqlite",
            "chunk_size_mb": 0.0001,  # ~100-byte windows: exercises chunked BLOB streaming
            "userdata_columns": {"nvarchar1": "Title", "tp_ContentType": "ContentType"},
            "content_type_field": "ContentType",
        }},
        "sink": {"type": "local_folder", "options": {"root": "out"}},
        "mapping": {
            "classes": {"Invoice": "Invoice", "Contract": "Contract"},
            "properties": {"Title": "DocumentTitle", "_source_id": "MigrationSourceId",
                           "_version_label": "SourceVersion"},
            "folder": "/Migrated/{directory}",
            "strip_path_prefixes": ["sites/fin"],
        },
        "steps": steps,
    }
    cfg.update(extra)
    return cfg


@pytest.fixture
def wss(tmp_path):
    make_wss_db(str(tmp_path / "wss.db"))
    return tmp_path


def by_status(m):
    return {k: v[0] for k, v in m.manifest.counts().items()}


# --------------------------------------------------------------------- tests
def test_wss_full_pipeline_with_versions_and_rolling(wss):
    cfg = wss_config(wss, [
        {"inventory": {"workers": 2}},
        {"filter": {"exclude_patterns": ["*/forms/*"]}},
        {"extract": {"staging_dir": "staging", "workers": 3}},
        {"load": {"workers": 3, "batch_size": 2}},
        {"verify": {"workers": 2, "report": "state/report.json"}},
    ], rolling={"chunk_docs": 2})
    m = Migration(cfg, str(wss))
    results = m.run()
    m2 = Migration(cfg, str(wss))
    counts = by_status(m2)
    # doc1: 3 versions, doc2: 1, doc3: 2, doc4 (Forms page) skipped
    assert counts == {"VERIFIED": 6, "SKIPPED": 1}
    assert any(r.get("chunk", 0) >= 2 for r in results), "rolling chunks should have looped"

    out = wss / "out" / "Migrated" / "Invoices"
    assert (out / "inv-001.pdf").read_bytes() == b"INVOICE-1-v1" * 40          # oldest version first
    assert (out / "inv-001.pdf;v1024").read_bytes() == b"INVOICE-1-v2" * 45
    assert (out / "inv-001.pdf;v1536").read_bytes() == b"INVOICE-1-v3" * 50     # current
    meta = json.loads((out / "inv-001.pdf;v1536.meta.json").read_text())
    assert meta["class"] == "Invoice"
    assert meta["previous"] == "Migrated/Invoices/inv-001.pdf;v1024"
    assert meta["properties"]["SourceVersion"] == "3.0"
    assert meta["properties"]["DocumentTitle"] == "Title inv-001.pdf"
    assert (wss / "out" / "Migrated" / "Invoices" / "2019" / "inv-002.pdf").exists()
    assert not os.listdir(wss / "staging") or all(
        not files for _, _, files in os.walk(wss / "staging")), "verified items are cleaned from staging"
    report = json.loads((wss / "state" / "report.json").read_text())
    assert report["totals"]["VERIFIED"]["count"] == 6


def test_filter_latest_versions(wss):
    cfg = wss_config(wss, ["inventory", {"filter": {"versions": "latest"}}, "load", "verify"])
    Migration(cfg, str(wss)).run()
    counts = by_status(Migration(cfg, str(wss)))
    assert counts == {"VERIFIED": 4, "SKIPPED": 3}
    # latest version only, loaded as a brand-new document (no ;v suffix)
    assert (wss / "out" / "Migrated" / "Invoices" / "inv-001.pdf").read_bytes() == b"INVOICE-1-v3" * 50


def test_dynamic_step_selection_and_dry_run(wss):
    cfg = wss_config(wss, ["inventory", "filter", "extract", "load", "verify"])
    m = Migration(cfg, str(wss))
    res = m.run(dry_run=True)
    assert [r["step"] for r in res] == ["inventory", "filter", "extract", "load", "verify"]
    assert res[2]["skipped"] == "dry-run" and res[3]["skipped"] == "dry-run"
    m = Migration(cfg, str(wss))
    assert by_status(m) == {"PENDING": 7}
    est = m.estimate(docs_per_sec=7, link_gbps=1)
    assert est["remaining_docs"] == 7 and est["load_time"] == "0m 1s"
    # now only load + verify, streaming straight from the source (extract not in the run)
    Migration(cfg, str(wss)).run(steps=["load", "verify"])
    assert by_status(Migration(cfg, str(wss))) == {"VERIFIED": 7}


def test_filesystem_stream_mode_and_delta(tmp_path):
    src = tmp_path / "share"
    (src / "HR").mkdir(parents=True)
    (src / "Legal" / "2020").mkdir(parents=True)
    (src / "readme.txt").write_text("root file")
    (src / "HR" / "policy.pdf").write_bytes(b"policy v1")
    (src / "Legal" / "2020" / "nda.docx").write_bytes(b"nda")
    cfg = {"manifest": "m.db", "source": {"type": "filesystem", "options": {"root": "share"}},
           "sink": {"type": "local_folder", "options": {"root": "out"}},
           "steps": ["inventory", "load", "verify"]}
    Migration(cfg, str(tmp_path)).run()
    assert by_status(Migration(cfg, str(tmp_path))) == {"VERIFIED": 3}

    import time
    time.sleep(1.1)
    (src / "HR" / "policy.pdf").write_bytes(b"policy v2 - changed")
    (src / "HR" / "new.pdf").write_bytes(b"brand new")
    Migration(cfg, str(tmp_path)).run(steps=["delta", "load", "verify"])
    m = Migration(cfg, str(tmp_path))
    assert by_status(m) == {"VERIFIED": 5}
    assert (tmp_path / "out" / "HR" / "policy.pdf;v2").read_bytes() == b"policy v2 - changed"
    assert (tmp_path / "out" / "HR" / "policy.pdf").read_bytes() == b"policy v1"


@register_sink("flaky_test_sink")
class FlakySink(LocalFolderSink):
    fail_names = {"inv-002.pdf"}

    def load_batch(self, items):
        ok = [i for i in items if i.record.name not in self.fail_names]
        bad = [i for i in items if i.record.name in self.fail_names]
        out = super().load_batch(ok)
        return out + [LoadResult(i.record.source_id, error="simulated FileNet timeout") for i in bad]


def test_failures_retry(wss):
    cfg = wss_config(wss, ["inventory", {"filter": {"versions": "latest"}},
                           {"load": {"max_attempts": 2}}, "verify"])
    cfg["sink"]["type"] = "flaky_test_sink"
    Migration(cfg, str(wss)).run()
    m = Migration(cfg, str(wss))
    assert by_status(m)["FAILED"] == 1
    failed = next(m.manifest.iter_records([Status.FAILED]))[0]
    assert "simulated FileNet timeout" in failed.error and failed.attempts == 1
    Migration(cfg, str(wss)).run(steps=["load"])          # next run retries automatically
    assert Migration(cfg, str(wss)).manifest.get(failed.source_id).attempts == 2
    Migration(cfg, str(wss)).run(steps=["load"])          # max_attempts reached: left alone
    assert Migration(cfg, str(wss)).manifest.get(failed.source_id).attempts == 2
    FlakySink.fail_names = set()
    assert cli_main(["retry", "-c", _write(wss, cfg)]) == 0
    Migration(cfg, str(wss)).run(steps=["load", "verify"])
    assert by_status(Migration(cfg, str(wss))) == {"VERIFIED": 4, "SKIPPED": 3}


def test_csv_manifest_source(tmp_path):
    files = tmp_path / "files"
    files.mkdir()
    (files / "a.pdf").write_bytes(b"AAA")
    (files / "b.pdf").write_bytes(b"BBBB")
    (tmp_path / "export.csv").write_text(
        "DocumentId,FileName,StoragePath,DocType,CustomerNo,LastModified\n"
        "D1,a.pdf,a.pdf,INV,C-77,2021-05-01 10:00:00\n"
        "D2,b.pdf,b.pdf,CON,C-88,2021-06-01 10:00:00\n")
    cfg = {"manifest": "m.db",
           "source": {"type": "csv_manifest", "options": {
               "path": "*.csv", "content_root": "files",
               "columns": {"id": "DocumentId", "name": "FileName", "file": "StoragePath",
                           "content_type": "DocType", "modified": "LastModified"}}},
           "sink": {"type": "local_folder", "options": {"root": "out"}},
           "mapping": {"classes": {"INV": "Invoice"}, "properties": {"CustomerNo": "CustomerNumber"},
                       "folder": "/{content_type}"},
           "steps": ["inventory", "load", "verify"]}
    Migration(cfg, str(tmp_path)).run()
    meta = json.loads((tmp_path / "out" / "INV" / "a.pdf.meta.json").read_text())
    assert meta["class"] == "Invoice" and meta["properties"]["CustomerNumber"] == "C-77"
    assert json.loads((tmp_path / "out" / "CON" / "b.pdf.meta.json").read_text())["class"] == "Document"


# --------------------------------------------------------------------- FileNet sink (real HTTP)
def test_filenet_graphql_sink_end_to_end_over_http(wss):
    with FakeFileNet() as fn:
        cfg = wss_config(wss, ["inventory", {"filter": {"exclude_patterns": ["*/forms/*"]}},
                               {"load": {"workers": 1, "batch_size": 10}}, "verify"])
        cfg["sink"] = {"type": "filenet_graphql", "options": {
            "endpoint": fn.endpoint, "repository": "OS1",
            "auth": {"type": "basic", "username": "u", "password": "p"}}}
        Migration(cfg, str(wss)).run()
        m = Migration(cfg, str(wss))
        assert by_status(m) == {"VERIFIED": 6, "SKIPPED": 1}

        first = fn.uploads[0]["query"]
        assert first.count("createDocument(") == 3          # 3 new documents in ONE request
        assert 'classIdentifier: "Invoice"' in first and 'fileInFolderIdentifier: "/Migrated/Invoices"' in first
        assert '{MigrationSourceId: "doc1:512"}' in first
        assert "DocumentTitle" not in first.split("properties:")[1]  # sent as `name`, not duplicated
        assert b"INVOICE-1-v1" * 40 in fn.uploads[0]["files"].values()
        assert any("checkoutDocument" in q for q in fn.queries)
        assert any("checkinDocument" in u["query"] for u in fn.uploads)
        assert "/Migrated/Invoices/2019" in fn.folders
        uploads = [r for r in fn.requests if r["chunked"]]
        assert uploads, "uploads must be streamed with chunked transfer encoding"
        assert all(r["auth"] == "Basic dTpw" for r in fn.requests)
        assert all(r["xsrf"] == "tok123" for r in fn.requests[1:])   # cookie from the probe is echoed
        v3 = m.manifest.get("doc1:1536")
        assert v3.target_id.startswith("{DOC-") and v3.checksum


def test_filenet_partial_batch_failure_marks_only_failed_items(wss):
    with FakeFileNet() as fn:
        fn.fail_names = ["inv-002.pdf"]
        cfg = wss_config(wss, ["inventory", {"filter": {"versions": "latest"}}, {"load": {"workers": 1}}])
        cfg["sink"] = {"type": "filenet_graphql", "options": {"endpoint": fn.endpoint, "repository": "OS1"}}
        Migration(cfg, str(wss)).run()
        m = Migration(cfg, str(wss))
        counts = by_status(m)
        assert counts["LOADED"] == 3 and counts["FAILED"] == 1
        failed = next(m.manifest.iter_records([Status.FAILED]))[0]
        assert failed.name == "inv-002.pdf" and "simulated failure" in failed.error


def test_cmis_source_over_http(tmp_path):
    with FakeCmis() as cm:
        cfg = {"manifest": "m.db",
               "source": {"type": "cmis", "options": {"url": cm.url + "/cmis/browser", "folders": ["/Docs"],
                                                      "include_versions": True}},
               "sink": {"type": "local_folder", "options": {"root": "out"}},
               "mapping": {"classes": {"D:acme:report": "Report"}, "properties": {"acme:region": "Region"}},
               "steps": ["inventory", "load", "verify"]}
        Migration(cfg, str(tmp_path)).run()
        assert by_status(Migration(cfg, str(tmp_path))) == {"VERIFIED": 3}
    out = tmp_path / "out" / "Docs"
    assert (out / "report.pdf").read_bytes() == b"REPORT v1"
    assert (out / "report.pdf;v2").read_bytes() == b"REPORT v2 longer"
    assert (out / "2024" / "note.txt").read_bytes() == b"a note"
    meta = json.loads((out / "report.pdf;v2.meta.json").read_text())
    assert meta["class"] == "Report" and meta["properties"]["Region"] == "EMEA"


def test_cli_init_steps_status(tmp_path, capsys):
    out = tmp_path / "m.toml"
    assert cli_main(["init", "fileshare_to_filenet", "-o", str(out)]) == 0
    assert "filesystem" in out.read_text()
    assert cli_main(["steps"]) == 0
    printed = capsys.readouterr().out
    for word in ("inventory", "delta", "wss_sql", "cmis", "s3", "csv_manifest", "filenet_graphql"):
        assert word in printed


def _write(base, cfg):
    path = base / "cfg.json"
    path.write_text(json.dumps(cfg))
    return str(path)


def test_generic_sql_blob_source_and_cli_run(tmp_path, capsys):
    db = sqlite3.connect(str(tmp_path / "dms.db"))
    db.executescript("""
      CREATE TABLE Documents (DocId TEXT, Version INT, FileName TEXT, Cabinet TEXT, PolicyNo TEXT, Modified TEXT);
      CREATE TABLE DocumentData (DocId TEXT, Version INT, Data BLOB);
      INSERT INTO Documents VALUES ('P1', 1, 'policy.pdf', 'CAB1', 'POL-1', '2022-01-01T00:00:00'),
                                   ('P1', 2, 'policy.pdf', 'CAB1', 'POL-1', '2022-02-01T00:00:00'),
                                   ('P2', 1, 'claim.tif',  'CAB2', 'POL-2', '2022-03-01T00:00:00');
      INSERT INTO DocumentData VALUES ('P1', 1, X'01020304'), ('P1', 2, X'0102030405'), ('P2', 1, X'FFFF');
    """)
    db.commit()
    db.close()
    cfg = {"manifest": "m.db",
           "source": {"type": "sql_blob", "options": {
               "driver": "sqlite3", "database": "dms.db", "dialect": "sqlite",
               "partitions_query": "SELECT DISTINCT Cabinet FROM Documents",
               "documents_queries": [{"sql": "SELECT DocId AS id, Version AS version, FileName AS name, "
                                             "Cabinet AS directory, Modified AS modified, PolicyNo "
                                             "FROM Documents WHERE Cabinet = ? {since_filter}",
                                      "since_column": "Modified"}],
               "content": {"default": {"blob_query": "SELECT Data FROM DocumentData WHERE DocId = ? AND Version = ?",
                                       "params": ["id", "version"]}}}},
           "sink": {"type": "local_folder", "options": {"root": "out"}},
           "mapping": {"properties": {"PolicyNo": "PolicyNumber"}},
           "steps": ["inventory", "filter", "load", "verify"]}
    path = _write(tmp_path, cfg)
    assert cli_main(["run", "-c", path]) == 0
    assert (tmp_path / "out" / "CAB1" / "policy.pdf;v2").read_bytes() == bytes([1, 2, 3, 4, 5])
    meta = json.loads((tmp_path / "out" / "CAB2" / "claim.tif.meta.json").read_text())
    assert meta["properties"]["PolicyNumber"] == "POL-2"
    capsys.readouterr()
    assert cli_main(["status", "-c", path]) == 0
    assert "VERIFIED" in capsys.readouterr().out
