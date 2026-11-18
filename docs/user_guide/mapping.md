# Mapping

The `[mapping]` section turns each source record into a FileNet **class**, a set of
**properties** and, optionally, a **folder**.

```toml
[mapping]
default_class = "Document"
title_property = "DocumentTitle"
folder = "/Migrated/{directory}"
strip_path_prefixes = ["sites/finance"]

[mapping.classes]                     # source content type -> class
Invoice = "Invoice"
Contract = "Contract"
"*" = "Document"                      # optional catch-all

[mapping.properties]                  # source field -> target property
Title = "DocumentTitle"
InvoiceDate = { target = "InvoiceDate", type = "datetime" }
CustomerNo = { target = "CustomerNumber", type = "string", max_length = 64 }
_source_id = "MigrationSourceId"
_modified = { target = "SourceModified", type = "datetime" }
_version_label = "SourceVersion"
```

## Classes

`content_type` comes from the source: the SharePoint library title or content type (`wss_sql`),
the CMIS object type (`cmis`), the `content_type` column (`sql_blob`, `csv_manifest`) or the MIME
type (`filesystem`, `s3`). It is looked up in `[mapping.classes]`; with no match, `"*"` applies,
then `default_class`.

## Properties

Source fields are the metadata the source provides (list columns, CMIS properties, extra SQL or CSV
columns) plus these built-in fields:

| Field | Value |
|---|---|
| `_name` | file name |
| `_path` | `/directory/name` |
| `_directory` | folder path in the source |
| `_size` | bytes |
| `_modified` | last-modified time (ISO 8601, UTC) |
| `_content_type` | as above |
| `_source_id` | unique id of this version in the source |
| `_series_id` | id of the document (all its versions) |
| `_version_index` | ordering number of this version |
| `_partition` | library, folder, CSV file... |
| `_version_label` | source version label (`wss_sql`, `cmis`) |

`type` converts the value: `string`, `int`, `float`, `bool`, `datetime` (sent as
`YYYY-MM-DDThh:mm:ssZ`), `date`. `default` fills empty values; `max_length` truncates strings.
`passthrough_unmapped = true` also sends every unmapped source property under its own name.

If nothing sets `title_property`, it is set to the file name.

## Folders

`folder` is a template. Fields: `{directory}` (after `strip_path_prefixes`), `{partition}`,
`{content_type}`, `{name}` and any source property. Leave `folder` out to load documents unfiled.

## Reviewing a mapping

Run with the `local_folder` sink first: every file gets a `.meta.json` sidecar with the class and
properties FileNet would receive.
