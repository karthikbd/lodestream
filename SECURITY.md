# Security Policy

## Supported versions and end of support

| Version | Security fixes |
|---------|----------------|
| 0.3.x   | ✅ yes: the latest minor release |
| older   | ❌ no: upgrade to the latest release |

Only the latest minor release line receives fixes. When a new minor version is released, the previous
one stops receiving security updates **on that day**; this is announced in [CHANGELOG.md](CHANGELOG.md).
Upgrading within 0.x keeps the configuration format unless the changelog says otherwise, so the upgrade
path is always "install the latest release". Before 1.0, minor versions may change behaviour; each
change is listed in the changelog.

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Report vulnerabilities privately via GitHub's [Security Advisories](https://github.com/karthikbd/lodestream/security/advisories/new).

You can expect:
- **Acknowledgement** within 48 hours
- **Status update** within 7 days
- **Fix or mitigation** as soon as reasonably possible, coordinated with a disclosure date

## How reports are handled

1. **Acknowledge** within 48 hours and agree on a way to keep in touch.
2. **Triage** within 7 days: reproduce, assess severity (CVSS v4), and decide whether the report is a
   vulnerability in lodestream or in something it uses.
3. **Fix** on a private fork (GitHub Security Advisory), with a regression test. Target: 30 days for
   high and critical issues, 60 days for medium; low-severity issues may be fixed in the next release.
4. **Release** a patched version, then **publish** the advisory with a CVE (requested through GitHub)
   and list the fix under *Security* in the changelog.
5. **Credit** the reporter by name in the advisory and the release notes, unless they prefer otherwise.

Known vulnerabilities, fixed or not, are published as GitHub Security Advisories for this repository.
Vulnerabilities in dependencies that do **not** affect lodestream are recorded in the VEX document
[`vex.openvex.json`](vex.openvex.json) (OpenVEX), so scanners can tell users they need not act.

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
- CodeQL and OpenSSF Scorecard on every push to `main` and weekly; Dependabot for actions, CI tooling and the fuzzing image.
- ClusterFuzzLite fuzzing (Atheris) of config, mapping and GraphQL parsing on every pull request, push and daily.
- Releases: PyPI Trusted Publishing with provenance attestations; Sigstore-signed wheel, sdist and a
  CycloneDX SBOM (declaring the vendored driver) attached to each GitHub release, re-verified by
  `verify-release.yml`.

See the [Security page](https://lodestream.readthedocs.io/en/latest/user_guide/security.html)
of the documentation for permissions and TLS settings.

## Secrets and credentials used by the project

- **None are stored.** PyPI uploads use Trusted Publishing (short-lived OIDC tokens); release signing is
  keyless (Sigstore). The repository has no Actions secrets except GitHub's own `GITHUB_TOKEN`.
- `GITHUB_TOKEN` is read-only by default in every workflow (`permissions: read-all`); jobs ask for write
  access only for what they do (for example `id-token: write` in the publish job).
- Secret scanning with push protection is enabled; a leaked credential would be revoked at the issuer
  first, then removed from history.
- If a secret is ever needed, it is stored as a GitHub environment secret limited to the job that uses
  it, reviewed when a maintainer changes and rotated at least yearly.
- For users: lodestream reads credentials from environment variables or mounted files and never writes them
  to logs, reports or state files (see the documentation's Security page).
