# Release notes

## 0.2.0 (November 2026)

**Same supply-chain standard as mssql-ocp-migrate.**

- **No dependencies, no downloads.** `pip install lodestream` installs one package:
  - SQL Server sources use a **bundled** driver (python-tds 1.17.1, MIT, TLS on the standard
    library `ssl` module); pyodbc is used only if already installed.
  - The FileNet sink and the CMIS source use Python's standard library for HTTP instead of
    `requests`, and FileNet uploads are now **streamed** (chunked), so batch memory no longer grows
    with file size.
  - Configs are **TOML** (standard library, Python 3.11+) or JSON; YAML still works if PyYAML is
    already installed. `lodestream init` now writes `migration.toml`.
  - A test fails the build if any module imports an installer, a process launcher, or an HTTP
    client outside `_http.py`.
- **SQL Server connection options** for `wss_sql` and `sql_blob`: `host`, `port`, `instance`,
  `user`, `password_file` / `password_env`, `encrypt`, `trust_server_certificate`, `ca_file`,
  `hostname_in_certificate`.
- **Unknown config keys are rejected** at the top level and in `[mapping]`; a mapping `default`
  now also fills empty values.
- **End-to-end tests** in CI against SQL Server 2019, 2022 and 2025 with a WSS 3.0-shaped content
  database, a 30 MB BLOB, version history and a delta run.
- **Supply chain:** hash-locked CI tooling, CodeQL, OpenSSF Scorecard, weekly `pip-audit`, a
  CycloneDX SBOM and Sigstore signatures on every release, verified after publishing by
  `verify-release.yml`.
- **Documentation** at [lodestream.readthedocs.io](https://lodestream.readthedocs.io), with the
  CLI, configuration and plugin references generated from the code.
- `--version`, and `python -m lodestream`.

Upgrading from 0.1: convert YAML configs to TOML (or keep them and install PyYAML yourself); SQL
sources that used `connection_string` keep working through pyodbc.

## 0.1.0 (November 2026)

First release: steps `inventory`, `filter`, `extract`, `load`, `verify`, `delta`; sources
`wss_sql`, `sql_blob`, `filesystem`, `csv_manifest`, `s3`, `cmis`; sinks `filenet_graphql`,
`local_folder`; restartable SQLite manifest; CLI `init`, `steps`, `run`, `status`, `estimate`,
`retry`.
