# Limitations

| Area | Not migrated / not done | Workaround |
|---|---|---|
| Permissions | source ACLs and SharePoint permissions are not copied | set default instance security on the target classes, or apply security after the load with your own step |
| Audit history | who-did-what history in the source | export it separately if records rules need it |
| Workflows, alerts, list views | SharePoint and ECM application features | rebuild in FileNet / Business Automation |
| Links inside documents | references to old URLs are not rewritten | map `_source_id` to keep a lookup from old to new |
| Very large WSS farms | one manifest per run | run one configuration per content database |
| RBS (SharePoint 2010+) | content stored outside the database by Remote BLOB Storage | read through a `sql_blob` or custom source that resolves the RBS store |
| `s3` source metadata | `x-amz-meta-*` user metadata isn't read at inventory | a small custom source subclass |
| Created-by / created-date | not set on the FileNet document's system properties | map them to custom properties (`_modified`, source fields) |
| FileNet schema | classes and properties are not created | create them before the load |
