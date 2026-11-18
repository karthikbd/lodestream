# Testing

| Layer | Where | Needs |
|---|---|---|
| Unit and pipeline | `tests/test_lodestream.py`, `tests/test_config_and_drivers.py` | nothing: a WSS 3.0-shaped SQLite database, local folders |
| Over the wire | same files, with `tests/fakes.py` | nothing: in-process HTTP servers standing in for FileNet GraphQL and a CMIS repository; uploads are parsed from the real streamed multipart body |
| Guards | `tests/test_no_downloads.py` | nothing: no dependencies, no installer or process imports, HTTP only in `_http.py` |
| End to end | `tests/e2e/` | a real SQL Server (Docker) |

```console
$ pytest -q
$ docker compose -f tests/e2e/docker-compose.yml up -d
$ LODESTREAM_E2E=1 pytest tests/e2e -v
```

The end-to-end test creates a WSS 3.0-shaped content database (`image` columns), reads it with the
**bundled** driver (a 30 MB BLOB streamed in 4 MB windows, version history, Unicode, list
metadata), uploads to the FileNet stand-in over HTTP, then edits a document and checks that `delta`
adds it as a new version.

CI (`.github/workflows/`) runs: `tests.yml` (Python 3.10–3.13, ruff, mypy, and a warnings-as-errors
docs build), `e2e.yml` (SQL Server 2019, 2022 and 2025), `codeql.yml`, `scorecard.yml` and
`vulnerability-audit.yml`. All CI tooling is installed from hash-locked files in `ci/`; regenerate
them with:

```console
$ uv pip compile --universal --generate-hashes --python-version 3.10 ci/requirements-test.in -o ci/requirements-test.txt
```
