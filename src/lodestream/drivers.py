"""Database connections for SQL sources (``sql_blob`` and ``wss_sql``).

SQL Server is reached through one of two drivers; neither is ever installed by lodestream:

* ``pytds``  – bundled (``lodestream._vendor.pytds``), pure Python, always available.
* ``pyodbc`` – used only if *already installed* together with a Microsoft ODBC driver.

``driver = "auto"`` picks pyodbc when it is installed and the ODBC driver is registered,
otherwise the bundled pytds. ``sqlite3`` (tests, demos) and ``factory`` (your own DB-API
connection, e.g. Oracle or PostgreSQL) are also accepted.

Every connection returned here takes ``?`` placeholders, whatever the driver.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Sequence

from .utils import import_object

log = logging.getLogger("lodestream")

DRIVERS = ("auto", "pytds", "pyodbc", "sqlite3", "factory")


class DriverError(RuntimeError):
    pass


def resolve_password(o: Dict[str, Any]) -> Optional[str]:
    """``password_file`` (e.g. an OpenShift/Kubernetes Secret mount) > ``password_env`` > ``password``."""
    if o.get("password_file"):
        with open(o["password_file"], encoding="utf-8") as fh:
            return fh.read().strip()
    if o.get("password_env"):
        value = os.environ.get(o["password_env"])
        if value is None:
            raise DriverError(f"environment variable {o['password_env']} is not set")
        return value
    return o.get("password")


def _pyodbc_usable(odbc_driver: str) -> bool:
    try:
        import pyodbc  # optional, user-provided
    except Exception:
        return False
    try:
        return odbc_driver in pyodbc.drivers()
    except Exception:
        return False


def choose_driver(o: Dict[str, Any]) -> str:
    driver = o.get("driver", "auto")
    if o.get("connection_factory"):
        return "factory"
    if driver not in DRIVERS:
        raise DriverError(f"driver must be one of {', '.join(DRIVERS)}")
    if driver != "auto":
        return str(driver)
    if o.get("connection_string") or _pyodbc_usable(o.get("odbc_driver", "ODBC Driver 18 for SQL Server")):
        return "pyodbc"
    return "pytds"


class _QmarkCursor:
    """Cursor wrapper translating ``?`` placeholders to the bundled driver's ``%s``."""

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> Any:
        if params:
            from ._vendor.pytds.tds_types import Binary

            sql = sql.replace("%", "%%").replace("?", "%s")
            params = tuple(Binary(bytes(v)) if isinstance(v, (bytes, bytearray, memoryview)) else v
                           for v in params)
            self._raw.execute(sql, params)
        else:
            self._raw.execute(sql)
        return self

    def __getattr__(self, name: str) -> Any:
        return getattr(self._raw, name)


class _QmarkConnection:
    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def cursor(self) -> _QmarkCursor:
        return _QmarkCursor(self._raw.cursor())

    def close(self) -> None:
        self._raw.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._raw, name)


def _connect_pytds(o: Dict[str, Any]) -> Any:
    from ._vendor import pytds
    from ._vendor.pytds import tls

    host = o.get("host")
    if not host:
        raise DriverError("SQL Server source needs `host` (or a pyodbc `connection_string`)")
    instance = o.get("instance")
    kwargs = dict(  # noqa: C408 (keyword form reads like the driver's signature)
        dsn=f"{host}\\{instance}" if instance else host,
        port=None if instance else int(o.get("port", 1433)),
        database=o.get("database"), user=o.get("user"), password=resolve_password(o),
        login_timeout=int(o.get("login_timeout", 30)), timeout=o.get("query_timeout"),
        appname=o.get("app_name", "lodestream"), autocommit=True,
        bytes_to_unicode=True, disable_connect_retry=True,
        tls_server_hostname=o.get("hostname_in_certificate"),
    )
    encrypt = o.get("encrypt", "optional")
    if encrypt == "off":
        return _QmarkConnection(pytds.connect(**kwargs))
    cafile = tls.INSECURE if o.get("trust_server_certificate") else (o.get("ca_file") or tls.SYSTEM_CA)
    try:
        return _QmarkConnection(pytds.connect(cafile=cafile, validate_host=False, **kwargs))
    except Exception as exc:
        if encrypt == "optional" and "not supported by server" in str(exc):
            log.warning("%s does not support encryption; connecting unencrypted", host)
            return _QmarkConnection(pytds.connect(**kwargs))
        raise


def _connect_pyodbc(o: Dict[str, Any]) -> Any:
    import pyodbc  # optional, user-provided

    conn_str = o.get("connection_string")
    if not conn_str:
        server = o["host"] + (f"\\{o['instance']}" if o.get("instance") else f",{o.get('port', 1433)}")
        parts = [f"DRIVER={{{o.get('odbc_driver', 'ODBC Driver 18 for SQL Server')}}}", f"SERVER={server}",
                 f"DATABASE={o.get('database', '')}",
                 "Encrypt=" + {"off": "no", "optional": "optional", "required": "yes"}[o.get("encrypt", "optional")],
                 "TrustServerCertificate=" + ("yes" if o.get("trust_server_certificate") else "no")]
        if o.get("user"):
            parts += [f"UID={o['user']}", f"PWD={resolve_password(o) or ''}"]
        else:
            parts.append("Trusted_Connection=yes")
        conn_str = ";".join(parts) + ";"
    return pyodbc.connect(conn_str, autocommit=True)


def connect(o: Dict[str, Any], base_dir: str = ".") -> Any:
    """Open a DB-API connection described by a source's ``options``."""
    driver = choose_driver(o)
    if driver == "factory":
        factory = o["connection_factory"]
        factory = import_object(factory) if isinstance(factory, str) else factory
        return factory()
    if driver == "sqlite3":
        import sqlite3

        return sqlite3.connect(os.path.join(base_dir, o["database"]))
    if driver == "pyodbc":
        return _connect_pyodbc(o)
    return _connect_pytds(o)
