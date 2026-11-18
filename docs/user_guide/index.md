# User guide

The user guide covers each area of the package by topic. Each page stands on its own; read
{doc}`configuration` first if you're new.

```{toctree}
:maxdepth: 2

configuration
steps
sources
wss
filenet
mapping
performance
security
troubleshooting
limitations
plugins
```

| Page | Read it when you want to… |
|---|---|
| {doc}`configuration` | understand the config file, secrets and command-line overrides |
| {doc}`steps` | understand the manifest, each step, restarts, retries, rolling chunks and delta |
| {doc}`sources` | set up a file share, SQL, CSV, S3 or CMIS source |
| {doc}`wss` | migrate a WSS 3.0 / SharePoint content database |
| {doc}`filenet` | configure the FileNet sink, run a pilot, handle folders and versions |
| {doc}`mapping` | turn source content types and fields into FileNet classes and properties |
| {doc}`performance` | plan and run 100 TB: throughput, sizing, the playbook |
| {doc}`security` | handle permissions, secrets, TLS and staging data safely |
| {doc}`troubleshooting` | fix a specific error message |
| {doc}`limitations` | know what is not migrated |
| {doc}`plugins` | add your own source, sink or step |
