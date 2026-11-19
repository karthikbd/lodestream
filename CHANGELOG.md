# Changelog

## 0.3.0 (2026-11-18)

- New `lodestream check`: read-only pre-flight. Validates every SQL query against the real schema,
  samples records and streams content; validates every FileNet GraphQL operation against the server's
  introspected schema, the object store, and mapped classes and properties.
- End-to-end CI against pyodbc + ODBC Driver 18, an S3 server and Alfresco (CMIS).
- ClusterFuzzLite fuzzing; fixes for what it found: 4-digit years before 1000, `#` in GraphQL strings,
  folder templates validated at start-up, linear comment skipping in the check parser.
- CI tool locks no longer pin vulnerable versions for Python versions their jobs never use.
- Short name suffixes (truncated names, local-folder name clashes) use SHA-256 instead of SHA-1, so
  those suffixes differ from 0.2.0. No SHA-1 or MD5 is used anywhere.
- Private vulnerability reporting enabled; OpenSSF Best Practices passing badge.
- CONTRIBUTING.md.

## 0.2.0 (2026-11-18)

Same supply-chain standard as mssql-ocp-migrate.

- No runtime dependencies: SQL Server sources use a bundled driver (python-tds 1.17.1, TLS on the
  standard library); FileNet and CMIS use the standard library for HTTP; pyodbc, boto3 and PyYAML are
  used only if already installed. A test enforces it.
- FileNet uploads are streamed (chunked multipart); batch memory no longer grows with file size.
- Configs are TOML (Python 3.11+) or JSON; YAML if PyYAML is installed. `init` writes `migration.toml`.
- SQL Server connection options: `host`, `port`, `instance`, `user`, `password_file`, `password_env`,
  `encrypt`, `trust_server_certificate`, `ca_file`, `hostname_in_certificate`.
- Unknown config keys are rejected; mapping `default` also fills empty values.
- `--version`; `python -m lodestream`.
- End-to-end tests against SQL Server 2019, 2022 and 2025 with a WSS 3.0-shaped database.
- Hash-locked CI tooling, CodeQL, OpenSSF Scorecard, weekly pip-audit, CycloneDX SBOM, Sigstore
  signatures and release verification.
- Documentation site on Read the Docs, with generated CLI, configuration and plugin references.

## 0.1.0 (2026-11-18)

First release.

- Steps: `inventory`, `filter`, `extract`, `load`, `verify`, `delta`. Choose them per run with `--steps` or `Migration.run(steps=[...])`; `rolling` mode runs extract/load/verify in chunks.
- Sources: `wss_sql` (WSS 3.0 content DB), `sql_blob` (any DB with BLOBs), `filesystem`, `csv_manifest`, `s3`, `cmis`.
- Sinks: `filenet_graphql` (batched Content Services GraphQL), `local_folder`.
- SQLite manifest makes runs restartable; failed items retry on later runs; reconciliation report.
- CLI: `init`, `steps`, `run`, `status`, `estimate`, `retry`.
