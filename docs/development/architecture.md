# Architecture

```text
 SOURCE (plugin)                  STEPS (plugins, any subset, any order)              SINK (plugin)
 ───────────────                  ──────────────────────────────────────              ─────────────
 wss_sql   sql_blob               inventory → filter → [extract] → load → verify     filenet_graphql
 filesystem csv_manifest               ▲                                │            local_folder
 s3        cmis                        └────── delta (cut-over catch-up)┘            your plugin
 your plugin
                                  MANIFEST (SQLite, WAL): one row per document version
```

| Module | Role |
|---|---|
| `pipeline.py` | `Migration`: loads the config, builds plugins, plans steps, runs them (rolling chunks, hooks, dry run), status and estimate |
| `manifest.py` | the SQLite manifest: records, statuses, keyset-paginated reads, run history |
| `models.py` | `DocumentRecord`, `Status` |
| `registry.py` | name → class tables for sources, sinks and steps; `@register_*` decorators |
| `config.py` | TOML / JSON / YAML loading, `${VAR}` expansion, key validation |
| `mapping.py` | content type → class, fields → properties, folder templates |
| `drivers.py` | SQL connections: bundled pytds, pyodbc if installed, sqlite3, factories; `?` placeholders everywhere |
| `_http.py` | the only HTTP code: urllib client with streamed multipart uploads; used by the FileNet sink and CMIS source |
| `sources/`, `sinks/`, `stages/` | the built-in plugins |
| `_vendor/pytds` | bundled python-tds 1.17.1 (see `THIRD_PARTY_NOTICES.md`) |

## Design rules

- **The manifest is the only state.** Every step reads work from it and writes outcomes back in
  small transactions, so any run can stop and restart.
- **One row per version; versions load in order.** The load step builds, per document, the chain
  of versions still to load after the last loaded one and stops at the first one that isn't ready.
- **Nothing is retried that could duplicate.** Uploads are not resent within a run; verification
  failures become `MISMATCH`, which is never retried automatically.
- **No dependencies, no downloads.** Only the standard library and bundled code; optional modules
  are imported inside functions and only if present. `tests/test_no_downloads.py` enforces it.
