# Troubleshooting

Before a run, `lodestream check -c migration.toml` finds most problems below without moving anything.
During and after a run, start with `lodestream status -c migration.toml`, then look at the failed items' errors. The
manifest is a SQLite file you can query directly:

```console
$ sqlite3 state/manifest.db "SELECT status, error, COUNT(*) FROM documents WHERE status IN ('FAILED','MISMATCH') GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 20"
```

## Configuration

| Message | Cause and fix |
|---|---|
| `unknown key(s) in the config file: ...` | a typo or a key at the wrong level. In TOML, a plain `key = value` written after a `[table]` header belongs to that table: put top-level keys such as `steps = [...]` before the first header. |
| `TOML configs need Python 3.11+` | on Python 3.10, write the config as JSON. |
| `YAML configs need PyYAML` | lodestream doesn't install PyYAML; use TOML or JSON, or install PyYAML yourself. |
| `Unknown step(s) [...]` / `Unknown source type` | check the name with `lodestream steps`; a plugin module must be listed in `plugins`. |
| `delta needs a previous inventory run` | run `inventory` first, or give `since` in the delta step. |

## SQL sources

| Message | Cause and fix |
|---|---|
| `environment variable X is not set` | export the variable named in `password_env`, or use `password_file`. |
| login failed / timeout | check `host`, `port` (or `instance` with UDP 1434 open), firewall, and that the login has `db_datareader`. |
| certificate verify failed | the server's certificate isn't trusted: set `ca_file`, or `hostname_in_certificate` if connecting by another name; `trust_server_certificate = true` on test systems. |
| `Invalid column name` / `Invalid object name` | the database's schema differs from the built-in WSS 3.0 queries; override `documents_queries` or `content` (see {doc}`wss`). |
| `BLOB ended early at byte ...` | the content changed or was truncated while being read; rerun (the item is retried). |
| inventory counts lower than expected | compare with the source per library; check the `filter` reasons (`status` shows skipped counts, the manifest `error` column holds each reason). |

## FileNet

| Message | Cause and fix |
|---|---|
| `HTTP 401` / `403` | user, password or token; the user's rights on the object store and classes. |
| GraphQL `Cannot query field` / `Unknown argument` | the release's schema differs: compare in GraphiQL and override the template (see {doc}`filenet`). |
| property errors on create | the class lacks a mapped property, or the type differs; fix `[mapping.properties]` or the class. |
| `folder: Folder ... does not exist` | `create_folders = false` and the folder is missing. |
| `... (document left checked out; reservation ...)` | a check-in failed after the checkout; cancel the checkout in Administration Console, then `lodestream retry`. |
| `MISMATCH` after `verify` | the content size in FileNet differs from the source, or the content changed between `extract` and `load`. Check the document; never retried automatically. |

## Restarting

Stop a run at any time with Ctrl+C; in-flight batches finish and the manifest is consistent. Run
the same command again to continue. To retry failures: `lodestream retry -c migration.toml`, then
`lodestream run -c migration.toml --steps load,verify`.
