# Writing your own source, sink or step

Sources, sinks and steps are plugins registered by name. Put yours in a module, list it in
`plugins`, and refer to it by name in the config.

## A source

A source yields one `DocumentRecord` per document **version** and opens a binary stream for its
content:

```python
# mycompany/lodestream_ext.py
from lodestream import DocumentRecord, Source, register_source


@register_source("legacy_dms")
class LegacyDms(Source):
    """Our legacy DMS.

        [source]
        type = "legacy_dms"
        options = { base_url = "https://dms.internal", cabinet_filter = "FIN*" }
    """

    def partitions(self):                       # scanned in parallel by inventory
        return api.list_cabinets(self.options.get("cabinet_filter"))

    def iter_documents(self, partition, since=None):
        for d in api.list_docs(partition, modified_after=since):
            yield DocumentRecord(
                source_id=f"{d.id}:{d.ver}",    # unique per version
                series_id=d.id,                 # same for all versions of a document
                version_index=d.ver,            # higher = newer (0 = let the manifest number them)
                name=d.filename, directory=d.folder, size=d.size,
                modified=d.modified, content_type=d.doctype,
                properties={"PolicyNo": d.policy},
                source_ref={"id": d.id, "ver": d.ver})

    def open_content(self, record):             # a readable binary stream; the caller closes it
        return api.download(record.source_ref["id"], record.source_ref["ver"])
```

```toml
plugins = ["mycompany.lodestream_ext"]

[source]
type = "legacy_dms"
options = { base_url = "https://dms.internal" }
```

`iter_documents` must honour `since` (only versions modified after it) for `delta` to work.

## A sink

```python
from lodestream import LoadResult, Sink, register_sink


@register_sink("my_target")
class MyTarget(Sink):
    """options: ..."""

    def open(self):
        self.client = connect(self.options["url"])

    def load_batch(self, items):
        results = []
        for item in items:      # item.record, item.target_class, item.properties, item.folder,
            try:                # item.previous_target_id (set => add a version to that document)
                with item.open() as stream:          # always read content through item.open()
                    new_id = self.client.create(item.target_class, item.properties, stream)
                results.append(LoadResult(item.record.source_id, target_id=new_id))
            except Exception as exc:
                results.append(LoadResult(item.record.source_id, error=str(exc)))
        return results

    def verify(self, record):
        return self.client.exists(record.target_id), "ok"
```

Reading content through `item.open()` is what computes the checksum stored in the manifest.

## A step

```python
from lodestream import Stage, Status, register_stage


@register_stage("tag_legal_hold")
class TagLegalHold(Stage):
    description = "Mark documents under legal hold so they are skipped."

    def run(self, ctx, limit=None):
        n = 0
        for page in ctx.manifest.iter_records([Status.PENDING]):
            hold = [{"source_id": r.source_id, "status": Status.SKIPPED, "error": "legal hold"}
                    for r in page if r.properties.get("LegalHold") == "Yes"]
            ctx.manifest.update(hold)
            n += len(hold)
        return {"processed": n}
```

Add it to `[[steps]]` like any built-in step. The registered name, the docstring and
`description` appear in `lodestream steps`.
