# Steps, the manifest and restarts

## The manifest

Every document **version** is one row in the manifest (SQLite, `manifest = ...`). Each step
reads its work from the manifest and writes the outcome back, so a run can be stopped at any
moment (Ctrl+C, a crashed pod, a reboot) and started again: it continues where it stopped.

```text
             inventory           extract            load             verify
 source ───────────────► PENDING ───────► EXTRACTED ───────► LOADED ───────► VERIFIED
                            │                 │                 │
                     filter │          failure│          failure│ verify fails
                            ▼                 ▼                 ▼               ▼
                         SKIPPED            FAILED ◄────────── FAILED        MISMATCH
                                              │ retried on the next run, up to max_attempts
```

| Status | Meaning |
|---|---|
| `PENDING` | found by `inventory` or `delta`; nothing done yet |
| `SKIPPED` | excluded by `filter`; the reason is stored in `error` |
| `EXTRACTED` | content copied to staging with its SHA-256 |
| `LOADED` | created in the target; `target_id` holds the FileNet id |
| `VERIFIED` | checked in the target |
| `FAILED` | extract or load failed; retried automatically on later runs until `max_attempts` |
| `MISMATCH` | loaded, but verification failed or the content changed between extract and load. **Never retried automatically**, so nothing is ever duplicated: review these by hand |

`lodestream status` prints the counts and recent runs; `lodestream retry` sends `FAILED` items
back to the queue with their attempts reset.

## The steps

| Step | Reads | Writes | Notes |
|---|---|---|---|
| `inventory` | the source | `PENDING` rows | partitions in parallel; re-running adds only new versions |
| `filter` | `PENDING` | `SKIPPED` | versions policy, path patterns, size, date, content type |
| `extract` | `PENDING` | `EXTRACTED` | optional; omit it to stream from the source |
| `load` | `EXTRACTED` (or `PENDING` without `extract`), retryable `FAILED` | `LOADED` / `FAILED` | batched, parallel; each document's versions oldest first |
| `verify` | `LOADED` | `VERIFIED` / `MISMATCH` | deletes verified staged copies; writes the report |
| `delta` | the source, changes only | `PENDING` rows | since the last inventory/delta, minus `overlap_minutes` |

Every option is listed in {doc}`/reference/plugins`.

### Versions are loaded in order

A document's versions share a `series_id` and are ordered by `version_index`. The first version
that reaches `load` creates the document; each later one is checked in on top of it. If an older
version of a document is not ready (still `PENDING`, or `FAILED` for good), its newer versions wait,
so the history in FileNet is never out of order. Different documents load fully in parallel.

### Rolling chunks

With `[rolling] chunk_docs = N`, consecutive `extract`, `load` and `verify` steps run as a loop
over N documents at a time until nothing is left. Staging then only ever holds about one chunk,
and the verified copies are deleted as it goes.

### Dry runs and estimates

`--dry-run` skips the steps that write (`extract`, `load`) and prints an estimate from the
manifest counts. `lodestream estimate -c migration.toml` does the same at any time, using the
throughput measured by the last `load` run unless you pass `--rate`.

## Cut-over pattern

1. Bulk: `lodestream run` while users keep working in the old system (days).
2. Freeze the old system (read-only).
3. Catch up: `lodestream run --steps delta,filter,extract,load,verify`. A changed document
   becomes a new version of the document already in FileNet; new documents are created.
4. Review `MISMATCH` and remaining `FAILED` items, keep `report.json` and the manifest as the
   audit record, and switch users over.
