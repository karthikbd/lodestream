import json
import sys

import pytest

from lodestream import drivers
from lodestream.cli import TEMPLATES
from lodestream.config import ConfigError, load_config, normalize_steps


@pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib is Python 3.11+")
@pytest.mark.parametrize("name", TEMPLATES)
def test_every_template_loads(name, monkeypatch):
    import lodestream
    from pathlib import Path

    monkeypatch.setenv("FN_USER", "alice")
    cfg = load_config(str(Path(lodestream.__file__).parent / "examples" / f"{name}.toml"))
    assert cfg["source"]["type"] and cfg["sink"]["type"] == "filenet_graphql"
    assert [n for n, _ in normalize_steps(cfg["steps"])][0] == "inventory"
    if cfg["sink"]["options"].get("auth", {}).get("type") == "basic":
        assert cfg["sink"]["options"]["auth"]["username"] == "alice"     # ${ENV} expanded


def test_json_and_env_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("NOPE", raising=False)
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"a": "${NOPE:-fallback}", "b": ["${NOPE}"]}))
    assert load_config(str(p)) == {"a": "fallback", "b": [""]}


def test_yaml_without_pyyaml_gives_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "yaml", None)
    p = tmp_path / "c.yaml"
    p.write_text("a: 1")
    with pytest.raises(ConfigError, match="PyYAML"):
        load_config(str(p))


def test_driver_choice(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyodbc", None)            # not installed
    assert drivers.choose_driver({}) == "pytds"
    assert drivers.choose_driver({"driver": "sqlite3"}) == "sqlite3"
    assert drivers.choose_driver({"connection_factory": "x:y"}) == "factory"
    with pytest.raises(drivers.DriverError):
        drivers.choose_driver({"driver": "oracle"})


def test_password_sources(tmp_path, monkeypatch):
    secret = tmp_path / "pw"
    secret.write_text("from-file\n")
    monkeypatch.setenv("PW", "from-env")
    assert drivers.resolve_password({"password_file": str(secret), "password_env": "PW"}) == "from-file"
    assert drivers.resolve_password({"password_env": "PW", "password": "x"}) == "from-env"
    assert drivers.resolve_password({"password": "x"}) == "x"
    monkeypatch.delenv("PW")
    with pytest.raises(drivers.DriverError):
        drivers.resolve_password({"password_env": "PW"})


def test_bundled_driver_takes_qmark_sql():
    calls = []

    class Raw:
        def execute(self, sql, params=None):
            calls.append((sql, params))

    cur = drivers._QmarkCursor(Raw())
    cur.execute("SELECT x FROM t WHERE a = ? AND b LIKE '50%' AND c = ?", ["k", b"\x00\x01"])
    sql, params = calls[0]
    assert sql == "SELECT x FROM t WHERE a = %s AND b LIKE '50%%' AND c = %s"
    assert params[0] == "k" and bytes(params[1]) == b"\x00\x01"
    cur.execute("SELECT 1")
    assert calls[1] == ("SELECT 1", None)


def test_pytds_connect_needs_a_host():
    with pytest.raises(drivers.DriverError, match="host"):
        drivers._connect_pytds({"database": "x"})


def test_mapping_defaults_types_and_catch_all():
    from lodestream.mapping import Mapper
    from lodestream.models import DocumentRecord

    m = Mapper({"classes": {"Invoice": "Inv", "*": "Other"},
                "properties": {"Region": {"target": "Region", "default": "NA"},
                               "Amount": {"target": "Amount", "type": "float"},
                               "_modified": {"target": "Mod", "type": "datetime"},
                               "Code": {"target": "Code", "max_length": 3}},
                "folder": "/M/{content_type}/{Region}"})
    r = DocumentRecord("s1", "s", 1, name="a.pdf", content_type="Letter", modified="2024-05-01T10:00:00",
                       properties={"Region": "", "Amount": "12.5", "Code": "ABCDEF"})
    cls, props, folder = m.map(r)
    assert cls == "Other"
    assert props == {"Region": "NA", "Amount": 12.5, "Mod": "2024-05-01T10:00:00Z", "Code": "ABC",
                     "DocumentTitle": "a.pdf"}
    assert folder == "/M/Letter"
    with pytest.raises(Exception, match="unknown key"):
        Mapper({"clases": {}})


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://host/x", "data:text/plain,hi", "relative/path"])
def test_http_client_refuses_non_http_urls(url):
    from lodestream._http import HttpClient
    with pytest.raises(ValueError, match="only http and https"):
        HttpClient().request("GET", url)
