# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.2.x   | ✅ Active  |
| 0.1.x   | ❌         |

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Report vulnerabilities privately via GitHub's [Security Advisories](https://github.com/karthikbd/lodestream/security/advisories/new).

You can expect:
- **Acknowledgement** within 48 hours
- **Status update** within 7 days
- **Fix or mitigation** as soon as reasonably possible, coordinated with a disclosure date

## Network access

`lodestream` has no telemetry and no update check, and downloads nothing. It declares **no runtime
dependencies** (the SQL Server driver is bundled), so `pip install` downloads nothing else. pyodbc,
boto3 and PyYAML are used only if they are already installed. Tests fail the build if any module
imports `pip` or `subprocess`, or if any module other than `_http.py` imports an HTTP client.

It opens connections only to the systems named in your configuration:

| Connection | Why |
|------------|-----|
| `[source.options]` SQL Server host, TCP (TDS) | `wss_sql` / `sql_blob`: read the content database |
| SQL Browser, UDP 1434 | only when `instance` is set, to resolve a named instance |
| `[sink.options] endpoint`, HTTPS | `filenet_graphql`: create documents, folders and versions; verify them |
| `[source.options] url`, HTTPS | `cmis`: read folders, documents and content |
| S3 endpoint, HTTPS (through boto3) | `s3`: list and read objects |

The `filesystem` and `csv_manifest` sources only read local or mounted files.

## Credentials and data

- Database passwords come from `password_file` (e.g. an OpenShift Secret mount), `password_env` or
  `password`; FileNet and CMIS credentials can be read from environment variables with `${VAR}` in the
  config. Credentials are never written to the manifest, the logs or the report.
- The manifest (`manifest.db`) holds document names, paths and metadata, never content. Keep it with
  the same care as the source system's metadata.
- The staging area used by the `extract` step holds plain copies of the documents. Put it on a
  protected volume; `verify` deletes staged copies once they are verified (`cleanup_staging`).
- TLS: SQL Server connections support `encrypt = "required"` with `ca_file` or the OS trust store;
  HTTPS endpoints are verified against the OS trust store or `verify_tls = "/path/ca.pem"`.
  `trust_server_certificate = true` and `verify_tls = false` exist for test systems only.

## Supply chain

- Every CI `pip install` is hash-locked (`ci/requirements-*.txt`); every GitHub Action is pinned to a commit SHA.
- `vulnerability-audit.yml`: `pip-audit` of the vendored python-tds and all CI tooling, weekly and on every change.
- CodeQL and OpenSSF Scorecard on every push to `main` and weekly; Dependabot for actions and CI tooling.
- Releases: PyPI Trusted Publishing with provenance attestations; Sigstore-signed wheel, sdist and a
  CycloneDX SBOM (declaring the vendored driver) attached to each GitHub release, re-verified by
  `verify-release.yml`.

See the [Security page](https://lodestream.readthedocs.io/en/latest/user_guide/security.html)
of the documentation for permissions and TLS settings.
