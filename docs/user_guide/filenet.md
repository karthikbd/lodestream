# The FileNet sink

`filenet_graphql` creates documents, versions and folders through the **Content Services GraphQL
API** of the FileNet Content Platform Engine (FileNet 5.5.x, Cloud Pak for Business Automation).
It uses only Python's standard library.

```toml
[sink]
type = "filenet_graphql"

[sink.options]
endpoint = "https://cpe.example.com/content-services-graphql/graphql"
repository = "OS1"                    # object store symbolic name or id
auth = { type = "basic", username = "${FN_USER}", password = "${FN_PASSWORD}" }
file_in_folder = true
create_folders = true
```

## How documents are sent

- **Batches.** `load` sends `batch_size` new documents (default 50) in **one** HTTP request: a
  GraphQL multipart request with one aliased `createDocument` mutation per document. Batches are
  also cut at `max_batch_mb` so very large files travel alone.
- **Streaming.** The request body is generated as it is sent (chunked transfer encoding), so a
  batch of large files is never held in memory.
- **Versions.** Later versions of a document are added with batched `checkoutDocument` followed by
  `checkinDocument` carrying the new content, oldest first.
- **Per-document results.** If FileNet rejects one document in a batch, only that document is
  marked `FAILED`; the others are `LOADED`.
- **No automatic upload retries.** An upload whose response is lost may still have created the
  documents, so it is not resent at once. The items are marked `FAILED` and retried on the next run
  (`max_attempts`). Map `_source_id` to a `MigrationSourceId` property so any duplicate can be found
  with one query.
- **XSRF.** If the server sets the `ECM-CS-XSRF-Token` cookie, it is sent back as a header on every
  request.

## Before the bulk run

Run the pre-flight check against the real server first:

```console
$ lodestream check -c migration.toml
[OK  ] sink    connect and authenticate (https://cpe.example.com/content-services-graphql/graphql)
[OK  ] sink    read the GraphQL schema
[OK  ] sink    GraphQL create document (createDocument) matches this server
[FAIL] sink    GraphQL check in (checkinDocument) matches this server
         Mutation.checkinDocument(documentProperties:).contentElements.replace[].type: CONTENT_TRANSFER is
         not a value of ContentElementType (has: CONTENT_REFERENCE, CONTENT_UPLOAD) -- override the template
[OK  ] sink    object store reachable
[OK  ] mapping class Invoice and its mapped properties exist
```

It reads the server's GraphQL schema by introspection and validates every operation, argument,
input field and enum value the sink will send, including templates you override. It also checks
that the object store answers and that each mapped class and property exists. Nothing is created.

Then:

1. Create a string property `MigrationSourceId` on the target classes and map `_source_id` to it
   (see {doc}`mapping`).
2. Create the target classes and properties you map to; lodestream does not change the FileNet
   schema.
3. Run a pilot of 10–20 documents, including one with versions:

   ```toml
   [[steps]]
   name = "filter"
   include_patterns = ["/sites/finance/invoices/2019/*"]
   ```

   Check the documents, versions, properties and folders in Administration Console.
4. Prepare the object store for a bulk load (see {doc}`performance`): content-based retrieval
   indexing, subscriptions, workflows and auditing are usually switched off during the load and on
   again afterwards. `[hooks]` can call your scripts for this.

## GraphQL differences between releases

The field and argument names used follow the Content Services GraphQL documentation, but they vary
slightly between FileNet and CP4BA releases. `lodestream check` names any mismatch exactly (operation,
argument, input field or enum value, with what the server has instead); override the template in the
config and run `check` again until it is clean:

| Option | Default operation |
|---|---|
| `create_template` | `createDocument(repositoryIdentifier, classIdentifier, fileInFolderIdentifier, documentProperties { name, contentElements, properties }, checkinAction)` |
| `checkout_template` | `checkoutDocument(repositoryIdentifier, identifier, checkoutAction) { reservation { id } }` |
| `checkin_template` | `checkinDocument(repositoryIdentifier, identifier, documentProperties, checkinAction)` |
| `verify_template` | `document(repositoryIdentifier, identifier) { id contentSize }` |
| `folder_get_template`, `folder_create_template` | `folder(...)`, `createFolder(...)` |
| `class_template` | `classDescription(...) { propertyDescriptions { symbolicName } }` (used by `check`) |

Templates use `<<placeholders>>` (for example `<<alias>>`, `<<repository>>`, `<<class>>`, `<<name>>`,
`<<properties>>`, `<<var>>`); the defaults are in `lodestream/sinks/filenet_graphql.py`.

## Folders

With `file_in_folder = true` and a `[mapping] folder` template, each document is filed into its
folder, and missing folders are created (`create_folders = true`). Filing is slower than leaving
documents unfiled; for archives that are found by search, `file_in_folder = false` loads fastest.

## Verification

`verify` looks every loaded document up by id and compares its content size with the manifest.
Anything that doesn't match is marked `MISMATCH` for review.

## Beyond about 500 documents per second

GraphQL over HTTPS has a ceiling per CPE node. Add CPE nodes or pods behind the load balancer and
raise `load.workers` first. For more, implement the same `Sink` interface over the CE Java API (EJB
transport), for example as a small loader service; every other part of the pipeline stays the same
(see {doc}`plugins`).
