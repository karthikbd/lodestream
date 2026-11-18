# Choosing a pipeline

## Which source?

| Your content lives in… | Source | Why |
|---|---|---|
| WSS 3.0 / MOSS 2007 (SharePoint) | `wss_sql` | Reads a **restored copy** of the content database directly: many times faster than SharePoint's web services, with versions and list metadata. See {doc}`/user_guide/wss`. |
| A home-grown DMS, an imaging system, any database with a BLOB column | `sql_blob` | You write the SQL; BLOBs are streamed in chunks. SQL Server works out of the box (bundled driver); other databases through a DB-API connection factory. |
| A file share, NFS or SMB mount | `filesystem` | One partition per top-level folder; a changed file becomes a new version. |
| Anything that can export "file path + metadata" | `csv_manifest` | The universal fallback: export a CSV from the old system, keep the files on a share. |
| S3, MinIO, NetApp StorageGRID, Ceph | `s3` | Needs boto3 already installed. Optionally every object version. |
| Alfresco, Documentum, OpenText, Nuxeo, SharePoint 2013+ CMIS | `cmis` | CMIS 1.1 browser binding, folder tree walk, optional version history. |
| Something else | your own | A source is a class with three methods; see {doc}`/user_guide/plugins`. |

## Stream or stage?

| | Stream (no `extract` step) | Stage (`extract` step) |
|---|---|---|
| Content path | source → FileNet | source → staging disk → FileNet |
| Disk needed | none | `max_staged_bytes` (rolling) or the full volume |
| Checksums | computed while uploading | computed at extract, re-checked at load (`MISMATCH` if the bytes changed) |
| Retries | re-read from the source | re-read from staging; the source is not touched again |
| Best when | the source is fast and close to FileNet (file share in the same data center) | the source is slow, remote or fragile (an old SQL Server, a WAN link), or loads must not hit it twice |

## Rolling chunks or not?

`rolling = { chunk_docs = 200000 }` runs extract → load → verify on 200,000 documents at a time, then
deletes the verified staged copies and moves on. Use it whenever staging can't hold everything;
at 100 TB that is almost always. Without it, each step runs once over everything.

## How many versions?

The `filter` step decides, before anything moves:

| `versions =` | Moves | Typical use |
|---|---|---|
| `"all"` | the full history | records with retention rules |
| `"last_n"` + `keep_versions = 3` | the newest N versions | most document libraries |
| `"latest"` | the current version only | archives, file shares |

Old versions are often a large share of a SharePoint content database. Run `--dry-run` with each
policy and compare the counts before deciding.
