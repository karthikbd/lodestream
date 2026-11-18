# Sources

A source lists document versions (`inventory`, `delta`) and opens a stream for each one's
content. All sources produce the same records, so every step, the mapping and the sink work the
same whatever the source. The complete option list for each is in {doc}`/reference/plugins`.

## File shares: `filesystem`

```toml
[source]
type = "filesystem"
options = { root = "/mnt/legacy_share" }
```

- Each top-level folder is a partition, scanned in parallel; files directly under `root` form one
  more partition.
- The path relative to `root` identifies the document; its modification time identifies the
  version. A file changed after the bulk run is picked up by `delta` as a new version.
- Hidden files and folders are skipped unless `exclude_hidden = false`.

## Any SQL database with files in it: `sql_blob`

You describe the database with SQL; lodestream partitions it, streams the BLOBs in fixed-size
windows (`chunk_size_mb`), so a 2 GB file never sits in memory, and supports `delta` through a
`{since_filter}` token.

```toml
[source]
type = "sql_blob"

[source.options]
host = "legacydb"
database = "DMS"
user = "dms_reader"
password_env = "DMS_DB_PASSWORD"
partitions_query = "SELECT DISTINCT CabinetId FROM Documents"

[[source.options.documents_queries]]
since_column = "d.ModifiedOn"
sql = """
SELECT d.DocId AS id, d.Version AS version, d.FileName AS name, d.FolderPath AS directory,
       d.ByteSize AS size, d.ModifiedOn AS modified, d.DocType AS content_type,
       d.CustomerNo, d.PolicyNo
FROM Documents d WHERE d.CabinetId = ? {since_filter}"""

[source.options.content.default]
length_query = "SELECT {length}(Data) FROM DocumentData WHERE DocId = ? AND Version = ?"
chunk_query = "SELECT {substr}(Data, ?, ?) FROM DocumentData WHERE DocId = ? AND Version = ?"
params = ["id", "version"]
```

**Columns.** Alias the result columns to `id` (required: the logical document), `version` (higher
is newer), `name`, `directory`, `size`, `modified`, `content_type` and optionally `partition`.
Columns named `ref_*` are kept to fetch the content (a `ref_kind` column picks a different
`[content.<kind>]` entry per row). **Every other column becomes a metadata property** you can map.

**Partitions.** With `partitions_query`, each document query receives the partition value as its
first `?` parameter, and partitions are scanned in parallel.

**Content.** `chunk_query` receives `(start, length, *params)`; `{substr}` and `{length}` expand to
the right functions for `dialect` (`mssql`, `sqlite`, `postgres`, `oracle`). For small files only,
`blob_query` fetches the whole value at once.

**Connections.** SQL Server works with nothing installed (the bundled driver), or with pyodbc if
it is already installed; see {doc}`security` for TLS. For PostgreSQL, Oracle or anything else,
supply a function returning a DB-API connection:

```toml
[source.options]
connection_factory = "mycompany.dbs:oracle_connection"
dialect = "oracle"
```

## Any other system: `csv_manifest`

If an old system can export *file path + metadata* to CSV, it can be migrated:

```toml
[source]
type = "csv_manifest"

[source.options]
path = "./exports/*.csv"              # each CSV file is a partition
content_root = "/mnt/export/files"    # relative paths in the file column start here

[source.options.columns]              # your CSV headers
id = "DocumentId"
version = "VersionNo"
name = "FileName"
directory = "FolderPath"
file = "StoragePath"
modified = "LastModified"
content_type = "DocType"
```

Every column not named in `columns` becomes a property.

## Object storage: `s3`

```toml
[source]
type = "s3"
[source.options]
bucket = "legacy-archive"
prefix = "documents/"
endpoint_url = "https://minio.internal:9000"   # S3-compatible stores
include_versions = false
```

The `s3` source uses **boto3**, which lodestream never installs: install it yourself where the
migration runs. Credentials come from the usual AWS chain (environment, profile, instance role).

## ECM repositories: `cmis`

Alfresco, Documentum (with its CMIS service), OpenText, Nuxeo and SharePoint 2013+ (CMIS producer)
speak CMIS 1.1. lodestream uses the browser binding (JSON over HTTPS) through Python's standard
library:

```toml
[source]
type = "cmis"
[source.options]
url = "https://alfresco.example.com/alfresco/api/-default-/public/cmis/versions/1.1/browser"
username = "${CMIS_USER}"
password = "${CMIS_PASSWORD}"
folders = ["/Sites/finance/documentLibrary"]
include_versions = true
```

Each folder is a partition; the tree below it is walked. `content_type` is the CMIS object type
(e.g. `D:acme:invoice`), and custom properties (everything that isn't `cmis:*`) are available for
mapping.

## WSS / SharePoint

See {doc}`wss`.
