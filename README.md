# lodestream

[![PyPI version](https://badge.fury.io/py/lodestream.svg)](https://pypi.org/project/lodestream/)
[![Python versions](https://img.shields.io/pypi/pyversions/lodestream.svg)](https://pypi.org/project/lodestream/)
[![Tests](https://github.com/karthikbd/lodestream/actions/workflows/tests.yml/badge.svg)](https://github.com/karthikbd/lodestream/actions/workflows/tests.yml)
[![End-to-end](https://github.com/karthikbd/lodestream/actions/workflows/e2e.yml/badge.svg)](https://github.com/karthikbd/lodestream/actions/workflows/e2e.yml)
[![Docs](https://readthedocs.org/projects/lodestream/badge/?version=latest)](https://lodestream.readthedocs.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![ClusterFuzzLite](https://github.com/karthikbd/lodestream/actions/workflows/cflite_batch.yml/badge.svg)](https://github.com/karthikbd/lodestream/actions/workflows/cflite_batch.yml)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/karthikbd/lodestream/badge)](https://securityscorecards.dev/viewer/?uri=github.com/karthikbd/lodestream)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/16911/badge)](https://www.bestpractices.dev/projects/16911)

Move documents, with their versions and metadata, from **any content store into IBM FileNet**:
WSS / SharePoint content databases, any SQL database holding files, file shares, CSV exports from
any system, S3 and CMIS repositories, or your own source. Every document version is tracked in a
restartable manifest, steps can be chosen per run, and it is built for 100 TB and more.

**No downloads, ever.** The package declares no dependencies: the SQL Server driver (python-tds,
MIT) is bundled inside it, with TLS rebuilt on Python's own `ssl` module, and HTTP to FileNet and
CMIS uses the standard library. `pip install` pulls in nothing else. pyodbc, boto3 and PyYAML are
used if already installed; they are never required.

```
pip install lodestream                                                  # from PyPI
pip install --no-index --no-deps lodestream-0.3.0-py3-none-any.whl     # air-gapped: the one wheel
```

Documentation: **https://lodestream.readthedocs.io**

## How it works

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

| Step | What it does |
|---|---|
| `inventory` | scans the source (partitions in parallel) and registers every document version |
| `filter` | skips old versions, system files, junk, by path, size, date or type |
| `extract` | *optional*: copies content to staging with SHA-256 checksums; leave it out to stream |
| `load` | creates documents in FileNet in parallel batches; each document's versions oldest first |
| `verify` | checks every loaded document, cleans staging, writes a reconciliation report |
| `delta` | picks up what changed since the last scan: a changed document becomes a new version |

`rolling = { chunk_docs = 200000 }` runs extract → load → verify in chunks, so staging holds a
slice of the data instead of all 100 TB.

## Quick start

```bash
lodestream init wss_to_filenet -o migration.toml     # templates: wss / fileshare / csv / cmis / s3 / sql
# edit migration.toml: source connection, FileNet endpoint, class + property mapping
lodestream check -c migration.toml                   # read-only pre-flight against the real systems
lodestream run -c migration.toml --dry-run --rate 300 --gbps 10   # counts, then an estimate
lodestream run -c migration.toml                                  # full migration
lodestream status -c migration.toml
lodestream run -c migration.toml --steps delta,filter,extract,load,verify   # before cut-over
```

Python API:

```python
from lodestream import Migration

m = Migration.from_file("migration.toml")
m.run(steps=["inventory", "filter"])
print(m.estimate(docs_per_sec=300, link_gbps=10))
```

## WSS / SharePoint: the 100 TB path

In WSS every file and version is a BLOB in SQL Server, so `wss_sql` reads a **restored copy** of the
content database directly instead of going through SharePoint one HTTP request at a time:

1. Ship compressed `COPY_ONLY` backups to the FileNet data center and restore them there.
2. `--dry-run` for counts; `filter` away old versions and system files (`*/forms/*`, `*/_vti_*`...).
3. Prepare FileNet for the load: CBR indexing, subscriptions, workflows and auditing off; CPE nodes added.
4. Bulk run with rolling chunks; raise `load.workers` until FileNet's database or CPU is saturated.
5. Freeze WSS, run `delta`, switch users. Keep `report.json` and the manifest as the audit record.

See [WSS / SharePoint](https://lodestream.readthedocs.io/en/latest/user_guide/wss.html) and the
[100 TB playbook](https://lodestream.readthedocs.io/en/latest/user_guide/performance.html).

## FileNet

`filenet_graphql` uses the Content Services GraphQL API: N documents per request (aliased
`createDocument` mutations in one multipart upload, **streamed**), versions through checkout +
checkin, folders created as needed, per-document results, XSRF handled. Field names vary slightly
between FileNet / CP4BA releases, so every GraphQL operation is an overridable template, and
`lodestream check` validates all of them against your server's own schema (plus the object store and
every mapped class and property) before anything is loaded. See [the FileNet sink](https://lodestream.readthedocs.io/en/latest/user_guide/filenet.html).

## Security and supply chain

No runtime dependencies, no telemetry; connections go only to the systems in your config. Releases
are published with PyPI Trusted Publishing and carry provenance attestations, plus Sigstore-signed
assets and a CycloneDX SBOM (declaring the bundled driver) on GitHub. CI is hash-locked, runs a
weekly `pip-audit`, CodeQL and OpenSSF Scorecard. See [SECURITY.md](SECURITY.md).
Corporate networks: see the JFrog Artifactory / Curation notes in the
[installation guide](https://lodestream.readthedocs.io/en/latest/getting_started/install.html).

## Development

```bash
pip install -e ".[test]" && pytest            # unit, pipeline and over-the-wire HTTP tests
docker compose -f tests/e2e/docker-compose.yml up -d
LODESTREAM_E2E=1 pytest tests/e2e -v           # real SQL Server with a WSS-shaped database
```

CI runs the end-to-end suite on every push against SQL Server 2019, 2022 and 2025 (bundled driver
and pyodbc + ODBC Driver 18), an S3 server and Alfresco over CMIS (`.github/workflows/e2e.yml`), and
fuzzes the parsing code with ClusterFuzzLite.

Releasing: bump the version in `pyproject.toml` and `src/lodestream/__init__.py`, update
`CHANGELOG.md` and `docs/whatsnew/index.md`, push `main`, then publish a GitHub release `vX.Y.Z`.
`.github/workflows/python-publish.yml` runs the tests and publishes to PyPI with Trusted Publishing
(environment `release`, no stored token).

Third-party notices: see `THIRD_PARTY_NOTICES.md`.
