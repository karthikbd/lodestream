# WSS / SharePoint content databases

The `wss_sql` source reads a **Windows SharePoint Services 3.0 / MOSS 2007** content database
directly. In WSS every file and every version is stored as a BLOB inside SQL Server, so reading
the database is many times faster than going through SharePoint's web services, WebDAV or the
object model, which handle one file per HTTP request.

## 1. Restore a copy, don't read production

Microsoft does not support queries against live SharePoint databases, and a bulk read would slow
users down. Take compressed `COPY_ONLY` backups of the content databases and restore them on a SQL
Server **in the same data center as FileNet**:

| Link | Moving 100 TB of backups at full speed |
|---|---|
| 1 Gbps | about 9–10 days |
| 10 Gbps | about 1 day |
| shipped disks | a few days, no network limit |

Moving the databases once is usually faster than reading them across the network for weeks.

## 2. Permissions

A SQL login with `db_datareader` on each restored content database. Nothing is written to it.

## 3. Configure

```toml
[source]
type = "wss_sql"

[source.options]
host = "sqlstage01"
database = "WSS_Content_Restored"
user = "lodestream_reader"
password_env = "WSS_DB_PASSWORD"
encrypt = "optional"
trust_server_certificate = true       # self-signed certificate on the staging server
include_versions = true
content_type_field = "ContentType"    # choose the FileNet class by SharePoint content type

[source.options.userdata_columns]     # AllUserData column -> property name
nvarchar1 = "Title"
tp_ContentType = "ContentType"
```

Several content databases: run one configuration (and manifest) per database, in parallel if the
FileNet side has capacity.

## What is read

| From | What |
|---|---|
| `AllDocs` | current files: name, folder, size, modified time, UI version, library |
| `AllDocStreams` | current content, streamed in `chunk_size_mb` windows |
| `AllDocVersions` | older versions and their content (`include_versions = true`) |
| `AllUserData` | list columns you name in `userdata_columns`, per version |
| `AllLists` | library titles (used as `content_type` unless `content_type_field` is set) |

Each library is a partition, scanned in parallel. Each record also carries `_version_label`, the
SharePoint version (`UIVersion` 1536 → `"3.0"`), which you can map to a property.

## Finding the list columns

`AllUserData` stores list columns in generic slots (`nvarchar1`, `datetime3`, `float2`...). Which
slot holds which column is defined per list. On the restored copy, open the library's fields in
`AllLists.tp_Fields`, or compare a few known items:

```sql
SELECT TOP 20 d.LeafName, u.nvarchar1, u.nvarchar2, u.datetime1, u.float1, u.tp_ContentType
FROM AllDocs d JOIN AllUserData u ON u.tp_ListId = d.ListId AND u.tp_ID = d.DoclibRowId
WHERE d.ListId = '<library id>' AND d.IsCurrentVersion = 1 AND u.tp_IsCurrentVersion = 1;
```

## What to filter out

SharePoint stores pages and system files next to documents. A good starting filter:

```toml
[[steps]]
name = "filter"
versions = "last_n"
keep_versions = 3
exclude_patterns = ["*/forms/*", "*/_catalogs/*", "*/_vti_*", "*.aspx", "*/~$*"]
min_size = 1
```

## Schema variations

The built-in queries follow the WSS 3.0 schema. Patch levels and later SharePoint versions differ
in places (SharePoint 2010+ uses `varbinary(max)` and can keep content outside the database with
RBS). Run `--steps inventory,filter` on one library first and compare the counts with the library
in SharePoint. Every query can be overridden in the config with the `sql_blob` options
(`partitions_query`, `documents_queries`, `content`), see {doc}`sources`.

## Tested

The end-to-end suite (`tests/e2e`) creates a WSS 3.0-shaped database on SQL Server 2019, 2022 and
2025 in CI, reads it with the bundled driver (including a 30 MB file and version history), loads it
over HTTP and runs a delta after an edit.
