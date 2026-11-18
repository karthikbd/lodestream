# 10 minutes to lodestream

This tour migrates a small file share. It first writes to a local folder so you can inspect
exactly what would be created, then switches the same configuration to FileNet. Every source
follows the same pattern; only the `[source]` section changes.

## 1. Write a configuration file

```console
$ lodestream init fileshare_to_filenet -o migration.toml
```

`init` copies one of six commented templates (`wss_to_filenet`, `fileshare_to_filenet`,
`csv_to_filenet`, `cmis_to_filenet`, `s3_to_filenet`, `sql_to_filenet`). For the first run, point
the source at the share and send the output to a local folder:

```toml
manifest = "./state/manifest.db"

[source]
type = "filesystem"
options = { root = "./share" }       # each top-level folder is scanned in parallel

[sink]
type = "local_folder"                # dry run: files + JSON metadata sidecars
options = { root = "./out" }

[mapping]
default_class = "Document"
folder = "/Migrated/{directory}"
properties = { _source_id = "MigrationSourceId" }

[[steps]]
name = "inventory"
workers = 8

[[steps]]
name = "filter"
exclude_patterns = ["*/thumbs.db", "*.tmp", "*/~$*"]
min_size = 1

[[steps]]
name = "load"
workers = 32

[[steps]]
name = "verify"
report = "./state/report.json"
```

Every key is listed in {doc}`/reference/config`, and every source, sink and step option in
{doc}`/reference/plugins`.

## 2. Find out what is there

```console
$ lodestream run -c migration.toml --dry-run --rate 300
INFO    Plan: inventory -> filter -> load -> verify
INFO    [inventory] 3 partition(s), 8 worker(s)
INFO    [inventory] done: {'partitions': 3, 'seen': 4, 'new': 4, ...}
INFO    [filter] done: {'examined': 4, 'skipped': 1, 'reasons': {'exclude pattern': 1}, ...}
INFO    [load] skipped (dry run)
...
{
  "remaining_docs": 3,
  "remaining_bytes": 21,
  "rate_docs_per_sec": 300.0,
  "load_time": "0m 0s"
}
```

A dry run scans the source into the **manifest**, applies the filter, and stops before anything
is written. `--rate` (documents per second) and `--gbps` (link speed) turn the counts into an
estimate. On a real share this is where you learn how many documents and versions there are,
and what the filter removes.

## 3. Migrate

```console
$ lodestream run -c migration.toml
INFO    [load] done: {'processed': 3, 'loaded': 3, 'failed': 0, 'mismatch': 0, ...}
INFO    [verify] done: {'processed': 3, 'verified': 3, 'mismatch': 0, ...}
```

The inventory runs again but adds nothing new: the manifest already knows every version, so a
run can always be stopped and started again. The output holds each file and a sidecar showing
the class and properties FileNet would receive:

```console
$ cat out/Migrated/Finance/2024/q3-report.pdf.meta.json
{
  "class": "Document",
  "properties": {
    "MigrationSourceId": "Finance/2024/q3-report.pdf@1795042254240967051",
    "DocumentTitle": "q3-report.pdf"
  },
  "series_id": "Finance/2024/q3-report.pdf",
  "version_index": 1,
  "previous": null
}
```

## 4. Check the status

```console
$ lodestream status -c migration.toml
Total documents/versions: 4
  SKIPPED                 1         1.0 B
  VERIFIED                3        21.0 B

Recent runs:
  #7    verify     2026-11-18T22:50:54  verified=3, mismatch=0
  #6    load       2026-11-18T22:50:54  loaded=3, failed=0, mismatch=0, docs_per_sec=2129.04
  ...
```

`state/report.json` holds the same totals, broken down by partition, for sign-off.

## 5. Switch to FileNet

Replace the sink, delete `state/` (it describes the local run) and run again:

```toml
[sink]
type = "filenet_graphql"

[sink.options]
endpoint = "https://cpe.example.com/content-services-graphql/graphql"
repository = "OS1"
auth = { type = "basic", username = "${FN_USER}", password = "${FN_PASSWORD}" }
```

```console
$ export FN_USER=... FN_PASSWORD=...
$ lodestream run -c migration.toml
```

Create the `MigrationSourceId` string property on the target class first, or remove it from
`[mapping.properties]`. Start with a pilot of a few documents (`--steps inventory,filter`, then
an `include_patterns` filter on one folder) and check the result in Administration Console
before the bulk run; see {doc}`/user_guide/filenet`.

## 6. Before the cut-over

Users kept working while the bulk ran. Pick up their changes, as new versions of the documents
already in FileNet:

```console
$ lodestream run -c migration.toml --steps delta,filter,load,verify
```

## Next

- {doc}`choosing` to pick the right source and pipeline shape
- {doc}`/user_guide/wss` for SharePoint / WSS content databases
- {doc}`/user_guide/performance` for 100 TB
