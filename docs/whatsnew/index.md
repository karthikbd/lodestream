# Release notes

## 0.3.1 (November 2026)

Security fixes found while writing the threat model, and the groundwork for the OpenSSF silver and
baseline badges.

- **`local_folder` sink path traversal.** Output paths were built from folder and file names taken from
  the source, so a name such as `../../x` could write outside the configured `root`. Unsafe path
  components are now refused (the item fails with a clear error) and every path is checked to stay
  under `root`. The FileNet sink and staging were not affected.
- **HTTP client** accepts only `http` and `https` URLs.
- Governance, code of conduct, roadmap, a security assurance case, dependency and scanning policy,
  support and end-of-life policy, and an OpenVEX document.
- Reproducible builds (checked in CI), `mypy --strict`, `ruff` security rules, an 80% coverage floor,
  DCO and dependency review on pull requests; `main` accepts changes only through pull requests.

## 0.3.0 (November 2026)

- **`lodestream check`**: read-only pre-flight against the real systems.
  - Source: every configured SQL query is run against the actual schema (a missing table or column is
    named before anything moves), sample records are read, and one document per content kind is streamed.
  - FileNet: connection and authentication; the server's GraphQL schema is read by introspection and every
    operation, argument, input field and enum value the sink will send (including overridden templates) is
    validated against it; the object store answers; mapped classes and properties exist.
- **End-to-end tests against more real systems**: pyodbc + Microsoft ODBC Driver 18 on SQL Server
  2019/2022/2025, an S3 server (with versions), and Alfresco Community over CMIS (with version history).
- **Fuzzing** with ClusterFuzzLite (Atheris) on every pull request, push and daily. It found and this
  release fixes:
  - dates before year 1000 were written with a 3-digit year that could not be read back;
  - a `#` inside a GraphQL string value was taken for a comment by the check parser;
  - malformed `[mapping] folder` templates (`{a.b}`, `{0}`, `{x:>5}`...) failed on every document
    instead of at start-up; they are now rejected with a clear message;
  - the check parser's comment skipping could backtrack exponentially.
- `CONTRIBUTING.md`; `main` is protected against force pushes and deletion.
- Short name suffixes use SHA-256 instead of SHA-1 (suffixes differ from 0.2.0).
- OpenSSF Best Practices passing badge; private vulnerability reporting enabled.

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
