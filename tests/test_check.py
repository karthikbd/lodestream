"""``lodestream check``: pre-flight checks against the source and target."""
import json
import sqlite3

from fakes import FakeFileNet, filenet_schema
from lodestream import Migration
from lodestream import _graphql as gql
from lodestream.cli import main as cli_main
from test_lodestream import make_wss_db, wss_config


def statuses(results):
    return {r.name: r.status for r in results}


def test_check_all_green_wss_to_filenet(tmp_path):
    make_wss_db(str(tmp_path / "wss.db"))
    with FakeFileNet() as fn:
        fn.classes = {"Invoice": ["DocumentTitle", "MigrationSourceId", "SourceVersion"],
                      "Contract": ["DocumentTitle", "MigrationSourceId", "SourceVersion"],
                      "Document": ["DocumentTitle", "MigrationSourceId", "SourceVersion"]}
        cfg = wss_config(tmp_path, ["inventory", "load"])
        cfg["sink"] = {"type": "filenet_graphql", "options": {"endpoint": fn.endpoint, "repository": "OS1"}}
        results = Migration(cfg, str(tmp_path)).check(sample=3)
        bad = [(r.name, r.detail) for r in results if r.status != "ok"]
        assert not bad, bad
        names = [r.name for r in results]
        assert "documents query 1: valid for this schema" in names and "documents query 2: valid for this schema" in names
        assert "content query 'current': stream one BLOB" in names and "content query 'version': stream one BLOB" in names
        assert any(n.startswith("GraphQL create document") for n in names)
        assert any(n.startswith("class Invoice") for n in names)
        assert not fn.uploads, "check must not create anything"
    m = Migration(cfg, str(tmp_path))
    assert m.manifest.counts() == {}, "check must not touch the manifest"


def test_check_reports_schema_drift_precisely(tmp_path):
    make_wss_db(str(tmp_path / "wss.db"))
    c = sqlite3.connect(str(tmp_path / "wss.db"))       # a patch level without tp_RowOrdinal
    c.execute("ALTER TABLE AllUserData RENAME COLUMN tp_RowOrdinal TO tp_Ordinal")
    c.commit()
    c.close()
    with FakeFileNet() as fn:
        fn.schema = filenet_schema(class_arg="classId")    # a release that renamed the argument
        fn.classes = {"Invoice": ["DocumentTitle"]}
        cfg = wss_config(tmp_path, ["inventory"])
        cfg["sink"] = {"type": "filenet_graphql", "options": {"endpoint": fn.endpoint, "repository": "OS1"}}
        results = {r.name: r for r in Migration(cfg, str(tmp_path)).check()}
    q1 = results["documents query 1: valid for this schema"]
    assert q1.status == "fail" and "tp_RowOrdinal" in q1.detail
    create = results["GraphQL create document (createDocument) matches this server"]
    assert create.status == "fail" and "classIdentifier" in create.detail and "classId" in create.detail
    assert results["GraphQL check out (checkoutDocument) matches this server"].status == "ok"
    assert results["class Contract and its mapped properties exist"].status == "fail"     # not in object store
    assert results["class Invoice and its mapped properties exist"].status == "warn"      # missing properties


def test_check_cli_exit_codes(tmp_path, capsys):
    (tmp_path / "share" / "A").mkdir(parents=True)
    (tmp_path / "share" / "A" / "x.txt").write_text("hello")
    cfg = {"manifest": "m.db", "source": {"type": "filesystem", "options": {"root": "share"}},
           "sink": {"type": "local_folder", "options": {"root": "out"}}, "steps": ["inventory", "load"]}
    p = tmp_path / "c.json"
    p.write_text(json.dumps(cfg))
    assert cli_main(["check", "-c", str(p)]) == 0
    out = capsys.readouterr().out
    assert "[OK  ] source  stream one document's content" in out and "0 failed" in out
    cfg["source"]["options"]["root"] = "missing"
    p.write_text(json.dumps(cfg))
    assert cli_main(["check", "-c", str(p)]) == 1
    assert "[FAIL]" in capsys.readouterr().out


def test_graphql_parser_and_validator():
    schema = filenet_schema()
    v = gql.SchemaValidator(schema.get)
    ok = gql.parse_operation('mutation($c0: String) { d0: createDocument(repositoryIdentifier: "OS1", '
                             'classIdentifier: "Invoice", documentProperties: { name: "a", contentElements: '
                             '{ replace: [ { type: CONTENT_TRANSFER, subContentTransfer: { content: $c0 } } ] } }, '
                             'checkinAction: {}) { id } }')
    assert v.validate("Mutation", ok) == []
    bad = gql.parse_operation('mutation { createDocument(repositoryIdentifier: "OS1", documentProperties: '
                              '{ contentElements: { replace: [ { type: CONTENT_BLOB } ] }, title: "x" }) { id size } }')
    errors = v.validate("Mutation", bad)
    assert any("CONTENT_BLOB is not a value" in e for e in errors)
    assert any("title: no such input field" in e for e in errors)
    assert any("size: no such field on Document" in e for e in errors)


def test_regressions_found_by_fuzzing():
    """Found by tests/fuzz: years before 1000 lost their 4-digit form; '#' inside a GraphQL string
    was taken for a comment."""
    from lodestream.mapping import _convert
    from lodestream.sinks.filenet_graphql import gql_literal
    from lodestream.utils import parse_dt, to_iso

    dt = parse_dt("0111-11-11T11:11:11")
    assert to_iso(dt) == "0111-11-11T11:11:11" and parse_dt(to_iso(dt)) == dt
    assert _convert("0099-01-02T03:04:05", {"type": "datetime"}) == "0099-01-02T03:04:05Z"
    assert _convert("0099-01-02", {"type": "date"}) == "0099-01-02"
    f = gql.parse_operation(f"query {{ folder(identifier: {gql_literal('/#Archive')}) {{ id }} }}")[0]
    assert f.args == {"identifier": "/#Archive"}


def test_bad_folder_templates_fail_at_startup():
    import pytest
    from lodestream.config import ConfigError
    from lodestream.mapping import Mapper

    for bad in ["/x/{@[{]}", "/x/{a.b}", "/x/{0}", "/x/{name!r}", "/x/{name:>10}", "/x/{", "/x/{}"]:
        with pytest.raises(ConfigError, match="folder template"):
            Mapper({"folder": bad})
    Mapper({"folder": "/Migrated/{partition}/{directory}/{{literal}}"})
