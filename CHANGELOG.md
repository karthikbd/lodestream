# Changelog

## 0.1.0 (2026-11-18)

First release.

- Steps: `inventory`, `filter`, `extract`, `load`, `verify`, `delta`. Choose them per run with `--steps` or `Migration.run(steps=[...])`; `rolling` mode runs extract/load/verify in chunks.
- Sources: `wss_sql` (WSS 3.0 content DB), `sql_blob` (any DB with BLOBs), `filesystem`, `csv_manifest`, `s3`, `cmis`.
- Sinks: `filenet_graphql` (batched Content Services GraphQL), `local_folder`.
- SQLite manifest makes runs restartable; failed items retry on later runs; reconciliation report.
- CLI: `init`, `steps`, `run`, `status`, `estimate`, `retry`.
