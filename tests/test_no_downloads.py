"""Guards the 'no downloads, no telemetry' promise: the package declares no dependencies, nothing
imports pip or subprocess, and only one module (``_http.py``) can speak HTTP. That module is used
only by the FileNet sink and the CMIS source, towards the URL in their configuration."""
import ast
import pathlib
import re
import sys

import lodestream

PKG = pathlib.Path(lodestream.__file__).parent
NEVER = {"pip", "ensurepip", "subprocess", "ftplib", "xmlrpc", "webbrowser", "importlib.metadata", "smtplib"}
HTTP = {"urllib", "http", "requests", "httpx", "aiohttp", "urllib3"}
HTTP_MODULE = "_http.py"
HTTP_USERS = {"sinks/filenet_graphql.py", "sources/cmis.py"}


def _imports(f: pathlib.Path):
    for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            yield from (a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                yield node.module
            elif node.module:
                yield "." * node.level + node.module


def test_no_installer_or_process_imports():
    hits = [f"{f.relative_to(PKG)}: {n}" for f in PKG.rglob("*.py") for n in _imports(f)
            if n in NEVER or n.split(".")[0] in NEVER]
    assert not hits, hits


def test_only_the_http_module_imports_http_clients():
    hits = [f"{f.relative_to(PKG)}: {n}" for f in PKG.rglob("*.py") if f.name != HTTP_MODULE
            for n in _imports(f) if n.split(".")[0] in HTTP]
    assert not hits, hits


def test_only_filenet_and_cmis_use_the_http_module():
    users = {f.relative_to(PKG).as_posix() for f in PKG.rglob("*.py")
             if any(n.lstrip(".") == "_http" for n in _imports(f))}
    assert users == HTTP_USERS, users


def test_third_party_imports_are_optional_only():
    """Outside the stdlib, only modules used *if already installed*: pyodbc, boto3, PyYAML, and
    the optional extras of the bundled driver (never required)."""
    allowed_optional = {"pyodbc", "boto3", "yaml", "tomllib", "ntlm_auth", "kerberos", "spnego", "winkerberos",
                        "namedlist", "recordtype", "bitarray", "OpenSSL"}
    stdlib = set(sys.stdlib_module_names)
    for f in PKG.rglob("*.py"):
        for n in _imports(f):
            if n.startswith("."):
                continue
            m = n.split(".")[0]
            assert m in stdlib or m == "lodestream" or m in allowed_optional, f"{f}: {m}"


def test_pyproject_declares_no_dependencies():
    pp = PKG.parent.parent / "pyproject.toml"
    if pp.exists():   # running from a source checkout
        assert re.search(r"^dependencies = \[\]", pp.read_text(), re.M)


def test_optional_imports_are_guarded():
    """pyOpenSSL is not needed: the bundled driver's TLS is rebuilt on the stdlib ssl module."""
    src = (PKG / "_vendor/pytds/tls.py").read_text()
    assert "OpenSSL" not in src.replace("pyOpenSSL", "")
