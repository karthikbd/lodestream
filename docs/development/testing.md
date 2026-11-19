# Testing

| Layer | Where | Needs |
|---|---|---|
| Unit and pipeline | `tests/test_lodestream.py`, `tests/test_config_and_drivers.py` | nothing: a WSS 3.0-shaped SQLite database, local folders |
| Over the wire | same files, with `tests/fakes.py` | nothing: in-process HTTP servers standing in for FileNet GraphQL and a CMIS repository; uploads are parsed from the real streamed multipart body |
| Guards | `tests/test_no_downloads.py` | nothing: no dependencies, no installer or process imports, HTTP only in `_http.py` |
| End to end | `tests/e2e/` | a real SQL Server (Docker), an S3 server, an Alfresco repository |
| Fuzzing | `tests/fuzz/` | Atheris; run by ClusterFuzzLite in CI |

```console
$ pytest -q
$ docker compose -f tests/e2e/docker-compose.yml up -d
$ LODESTREAM_E2E=1 pytest tests/e2e -v
```

End-to-end jobs in CI (`e2e.yml`):

| Job | Real system | What it proves |
|---|---|---|
| SQL Server 2019 / 2022 / 2025 × bundled driver / pyodbc | SQL Server container; Microsoft ODBC Driver 18 for the pyodbc runs | `check` all green; a WSS 3.0-shaped database (`image` columns, 30 MB BLOB in 4 MB windows, version history, Unicode, list metadata) loads over HTTP; `delta` adds an edit as a new version |
| S3 | Moto's S3 server over HTTP | latest-only and all-versions runs, a 25 MB object, folder markers skipped |
| CMIS | Alfresco Community 26.2 | the test creates folders, documents and a second major version through CMIS, then migrates them with history |

```console
$ LODESTREAM_E2E_S3=1 pytest tests/e2e/test_e2e_s3.py        # with moto_server -p 9000 running
$ docker compose -f tests/e2e/alfresco-compose.yml up -d
$ LODESTREAM_E2E_CMIS=1 pytest tests/e2e/test_e2e_cmis.py
```

Fuzzing (`tests/fuzz`, Atheris): config parsing and `${VAR}` expansion, mapping and dates, and
GraphQL rendering and parsing. `cflite_pr.yml` fuzzes the code a pull request changes;
`cflite_batch.yml` fuzzes longer on every push to `main` and daily. Locally:

```console
$ pip install atheris
$ python tests/fuzz/fuzz_graphql.py -max_total_time=60
```

CI (`.github/workflows/`) runs: `tests.yml` (Python 3.10–3.13, ruff, mypy, and a warnings-as-errors
docs build), `e2e.yml`, `cflite_pr.yml` / `cflite_batch.yml`, `codeql.yml`, `scorecard.yml` and
`vulnerability-audit.yml`. All CI tooling is installed from hash-locked files in `ci/`; regenerate
them with:

```console
$ uv pip compile --universal --generate-hashes --python-version 3.10 ci/requirements-test.in -o ci/requirements-test.txt
```
