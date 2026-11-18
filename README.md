# lodestream

[![PyPI version](https://badge.fury.io/py/lodestream.svg)](https://pypi.org/project/lodestream/)
[![Python versions](https://img.shields.io/pypi/pyversions/lodestream.svg)](https://pypi.org/project/lodestream/)
[![Tests](https://github.com/karthikbd/lodestream/actions/workflows/tests.yml/badge.svg)](https://github.com/karthikbd/lodestream/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Bulk content migration from any source into IBM FileNet.** Each step can be chosen at run time, the whole run is restartable, and it is built for very large volumes (designed for 100 TB+ migrations).

```
 SOURCE (pluggable)                 STEPS (pick any, in any order)                      SINK (pluggable)
 ───────────────────                ───────────────────────────────────────────          ─────────────────
 wss_sql      (WSS/SharePoint DB)   inventory → filter → [extract] → load → verify       filenet_graphql
 sql_blob     (any DB with BLOBs)        ▲                                  │            local_folder (dry runs)
 filesystem   (NFS/SMB/local)            └──────── delta (cutover catch-up) ┘            your own plugin
 csv_manifest (export from ANY system)
 s3           (S3 / MinIO / StorageGRID)          MANIFEST (SQLite): one row per document version
 cmis         (Alfresco, Documentum, OpenText…)   PENDING → EXTRACTED → LOADED → VERIFIED
 your own plugin                                  (+ SKIPPED / FAILED / MISMATCH)
```

## Install

```bash
pip install "lodestream[all]"          # or pick extras: [filenet] [wss] [sql] [s3] [cmis]
pip install --no-index --find-links ./wheels lodestream   # air-gapped: wheels copied into ./wheels
```

## Quick start

```bash
lodestream init wss_to_filenet -o migration.yaml     # templates: wss / fileshare / csv / cmis / s3 / sql
# edit migration.yaml: connection strings, FileNet endpoint, class + property mapping
lodestream run -c migration.yaml --dry-run --rate 300 --gbps 10   # inventory + filter only, then an estimate
lodestream run -c migration.yaml                                  # full migration
lodestream status -c migration.yaml
```

## Choosing steps dynamically

The `steps:` list in the config is the default plan. You can override it per run:

```bash
lodestream run -c migration.yaml --steps inventory,filter          # scope the migration first
lodestream run -c migration.yaml --steps extract,load,verify       # bulk move
lodestream run -c migration.yaml --steps delta,filter,load,verify  # final catch-up before cutover
lodestream retry -c migration.yaml && lodestream run -c migration.yaml --steps load,verify
```

Or from Python:

```python
from lodestream import Migration
m = Migration.from_file("migration.yaml")
m.run(steps=["inventory", "filter"])
print(m.estimate(docs_per_sec=400, link_gbps=10))
Migration.from_file("migration.yaml").run(steps=["load", "verify"])
```

| Step | What it does | Key options |
|---|---|---|
| `inventory` | Scans the source and registers every document version as PENDING. Partitions are scanned in parallel. | `workers`, `batch_size` |
| `filter` | Marks items you don't want as SKIPPED: old versions, junk paths, size, date and type. | `versions: all/latest/last_n`, `keep_versions`, `exclude_patterns`, `min_size`, `modified_after` |
| `extract` | *Optional.* Copies content to fast staging storage with SHA-256 checksums. Leave it out to stream content straight from the source into FileNet. | `staging_dir`, `workers`, `max_staged_bytes` |
| `load` | Creates documents in parallel, many per API call. Each document's versions load oldest to newest. | `workers`, `batch_size`, `max_batch_mb`, `max_attempts`, `retry_failed` |
| `verify` | Checks every loaded item in the target, cleans up staging, and writes a reconciliation report. | `workers`, `cleanup_staging`, `report` |
| `delta` | Re-scans only what changed since the last inventory. A changed document becomes a **new version** of the document already in FileNet. | `overlap_minutes`, `since` |

**Rolling mode** (`rolling: {chunk_docs: 200000}`) runs extract, load and verify in repeating chunks. Staging then holds only a small slice of the data at any time, instead of the full 100 TB.

## Sources

| Type | Use for | Notes |
|---|---|---|
| `wss_sql` | WSS 3.0 / MOSS 2007 content databases | Reads a **restored copy** of the content DB directly, which is many times faster than SharePoint's web services. Streams BLOBs in chunks. Includes version history and AllUserData metadata. Partitions are document libraries. |
| `sql_blob` | Any database that stores files as BLOBs | You write the SQL. Supports mssql, sqlite, postgres and oracle; chunked streaming; `{since_filter}` for delta. |
| `filesystem` | File shares, NFS, SMB, local disk | Each top-level folder is a partition. A changed file becomes a new version. |
| `csv_manifest` | **Any other system** | Export "file path + metadata" to CSV and point lodestream at it. Each CSV file is a partition. |
| `s3` | S3, MinIO, StorageGRID, Ceph | Optionally migrates every object version. |
| `cmis` | Alfresco, Documentum, OpenText, Nuxeo, SharePoint CMIS | CMIS 1.1 browser binding. Walks the folder tree; optionally includes versions. |

### Add your own source (about 20 lines)

```python
# mycompany/lodestream_ext.py
from lodestream import Source, DocumentRecord, register_source

@register_source("legacy_dms")
class LegacyDms(Source):
    def partitions(self):
        return api.list_cabinets()

    def iter_documents(self, partition, since=None):
        for d in api.list_docs(partition, modified_after=since):
            yield DocumentRecord(source_id=f"{d.id}:{d.ver}", series_id=d.id, version_index=d.ver,
                                 name=d.filename, directory=d.folder, size=d.size,
                                 modified=d.modified, content_type=d.doctype,
                                 properties={"PolicyNo": d.policy}, source_ref={"id": d.id, "ver": d.ver})

    def open_content(self, record):
        return api.download(record.source_ref["id"], record.source_ref["ver"])  # binary stream
```

```yaml
plugins: [mycompany.lodestream_ext]
source: {type: legacy_dms, options: {...}}
```

Custom sinks (`@register_sink`) and custom steps (`@register_stage`) work the same way.

## FileNet sink (`filenet_graphql`)

- Uses the **Content Services GraphQL API**. Each batch of N documents goes in **one** multipart request with N aliased `createDocument` mutations.
- New versions use batched `checkoutDocument` and `checkinDocument` calls.
- Creates folders as needed (`file_in_folder: false` skips folder filing for maximum speed).
- Sends `ECM-CS-XSRF-Token` automatically if the server issues one.
- **Validate on your server first.** GraphQL field names differ slightly between FileNet and CP4BA releases. Every query is a template you can override (`create_template`, `checkin_template`, `verify_template`, and so on). Run a 10-document pilot and check the results in Administration Console.
- Above roughly 500 docs/s, implement the same `Sink` contract over the CE Java API (EJB transport), for example as a small Java loader service. The rest of the pipeline stays the same.

## Mapping

```yaml
mapping:
  default_class: Document
  classes: {Invoice: Invoice, Contract: Contract}  # source content type / library / CMIS type -> class
  properties:
    Title: DocumentTitle
    InvoiceDate: {target: InvoiceDate, type: datetime}
    _source_id: MigrationSourceId                  # built-ins: _name _path _directory _size _modified
                                                   # _source_id _series_id _version_index _partition
  folder: "/Migrated/{directory}"                  # null = unfiled
  strip_path_prefixes: ["sites/finance"]
```

Create a `MigrationSourceId` string property in FileNet and map `_source_id` to it. That gives you an exact link from every FileNet document back to its source for audit and reconciliation.

## 100 TB playbook

1. **Move databases, not files.** Ship compressed SQL backups (or disks) to the FileNet data center and restore them there.
2. Run `--dry-run` to get document counts and an ETA. Use the `filter` step to drop old versions and junk before moving anything.
3. Prepare FileNet for the load: disable CBR indexing, subscriptions, workflows and auditing. Pre-size tablespaces and add CPE nodes. Hooks (`hooks.before.load`) can call your own admin scripts for this.
4. Bulk run with `rolling` chunks. Scale `load.workers` until the FileNet database or CPE CPU is saturated. Watch progress with `lodestream status` and `lodestream estimate`.
5. Fix or `retry` failures. Review MISMATCH items by hand: they are never retried automatically, to avoid duplicates.
6. Cutover: freeze the source, run `--steps delta,filter,load,verify`, then switch users over.
7. Re-enable CBR and reindex. Keep `report.json` and the manifest as the audit record.

## Operations notes

- **Restartable.** Stop the run at any time (Ctrl+C) and run it again; it continues from the manifest. Failed items are retried on later runs, up to `max_attempts`.
- **Manifest storage.** Keep the manifest on local SSD. SQLite in WAL mode handles 100M+ rows.
- **Batch memory.** Uploads with the `requests` library buffer each batch in memory, so `max_batch_mb` caps memory use per worker.
- **WSS schema.** The default WSS queries target the WSS 3.0 schema. Validate them on one library first and override them in the config if your patch level differs.

## Tests

```bash
pip install -e .[dev] && pytest
```

The suite includes a simulated WSS 3.0 content database, a fake FileNet GraphQL endpoint, versioning, delta, rolling chunks, failure and retry, CSV, generic SQL, and the CLI.

## Releasing

Bump the version in `pyproject.toml` and `src/lodestream/__init__.py`, update `CHANGELOG.md`, push `main`, then publish a GitHub release `vX.Y.Z`. `.github/workflows/python-publish.yml` runs the tests and publishes to PyPI with Trusted Publishing (environment `release`, no stored token), then attaches Sigstore-signed wheel and sdist files to the release.

For an internal artifact repository (JFrog Artifactory, Nexus): `python -m build && twine upload --repository-url https://<artifactory>/api/pypi/<repo> dist/*`.
