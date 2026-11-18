# Performance and the 100 TB playbook

At this scale the **number of documents** limits the load more than the number of bytes: every
document is an API call, a database row and an index entry in FileNet. Plan around documents per
second.

## Planning numbers

Measure your own rate on a pilot (`lodestream estimate` uses the rate of the last `load` run). As a
planning guide for 100 TB:

| Average file size | Documents | At 100 docs/s | At 500 docs/s |
|---|---|---|---|
| 1 MB | ~100 million | ~12 days | ~2.3 days |
| 5 MB | ~20 million | ~2.3 days | ~11 hours |

Bytes matter for the network and staging: 100 TB takes about 9–10 days over 1 Gbps at full speed,
about a day over 10 Gbps.

```console
$ lodestream run -c migration.toml --dry-run --rate 300 --gbps 10
$ lodestream estimate -c migration.toml --gbps 10
```

## The playbook

1. **Move databases, not files.** For SQL-backed sources (WSS, document databases), ship
   compressed backups to the FileNet data center and restore them there; read locally.
2. **Count and cut.** `--dry-run` gives document and byte counts. Use `filter` to drop old versions,
   system files and junk before anything moves; old versions are often a large share of the volume.
3. **Prepare FileNet.**
   - Switch off content-based retrieval (CBR) indexing, subscriptions, workflow launches and
     auditing for the load; reindex afterwards.
   - Pre-size the object store database (tablespaces, transaction log) and update statistics.
   - Put storage areas on fast storage close to the CPE nodes.
   - Add CPE nodes or pods behind the load balancer for the migration window, and raise their JVM
     heap and connection pools.
   - Hooks (`[hooks] before.load`, `after.verify`) can run your admin scripts.
4. **Run the bulk with rolling chunks.** `[rolling] chunk_docs = 200000` keeps staging small.
   Raise `load.workers` (start at 16–32) until the FileNet database or CPE CPU is saturated, not
   further. Watch `lodestream status`.
5. **Repair.** `lodestream retry`, then `--steps load,verify`. Review `MISMATCH` items by hand.
6. **Cut over.** Freeze the source, `--steps delta,filter,extract,load,verify`, switch users.
7. **Clean up.** Re-enable CBR and reindex. Keep `report.json` and the manifest as the audit record.

## Tuning knobs

| Knob | Effect |
|---|---|
| `inventory.workers` | partitions scanned in parallel (libraries, top-level folders, CSV files) |
| `extract.workers` | parallel reads from the source into staging |
| `load.workers` | parallel upload threads; the main throughput knob |
| `load.batch_size` | documents per API request (default 50); fewer round trips |
| `load.max_batch_mb` | caps a batch's size so large files travel alone |
| `source chunk_size_mb` | BLOB window for SQL sources (default 8 MB) |
| `sink file_in_folder = false` | skips folder filing, the slowest part of a create |
| `rolling.chunk_docs` | staging footprint vs. how often each step restarts |

## Running in OpenShift or Kubernetes

lodestream is a single command, so it runs well as a Job: build an image with
`pip install --no-index --no-deps lodestream-*.whl`, mount the manifest's folder and staging on a
persistent volume (a restarted Job resumes from the manifest), mount secrets as files
(`password_file`) or environment variables (`${VAR}`), and run
`lodestream run -c /config/migration.toml`. Keep the manifest on block storage (SSD), not NFS:
SQLite needs reliable file locking.

## The manifest at scale

SQLite in WAL mode handles 100M+ rows on a local SSD. One manifest serves one migration run; to
split work across machines, give each machine its own configuration and manifest (for example one
per content database or per group of libraries).
