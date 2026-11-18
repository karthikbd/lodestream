# Security

## Network access

lodestream has no telemetry and no update check, and downloads nothing. It declares **no runtime
dependencies**: the SQL Server driver is bundled, and pyodbc, boto3 and PyYAML are used only if
already installed. The test suite fails the build if any module imports `pip` or `subprocess`, or if
any module other than `_http.py` imports an HTTP client, and `_http.py` is used only by the FileNet
sink and the CMIS source.

It connects only to the systems named in your configuration:

| Connection | Why |
|---|---|
| SQL Server source host, TCP (TDS) | `wss_sql` / `sql_blob`: read the content database |
| SQL Browser, UDP 1434 | only when `instance` is set, to resolve a named instance |
| FileNet `endpoint`, HTTPS | `filenet_graphql`: create documents, folders and versions; verify them |
| CMIS `url`, HTTPS | `cmis`: read folders, documents and content |
| S3 endpoint, HTTPS (through boto3) | `s3`: list and read objects |

## Permissions

| System | Needs |
|---|---|
| SQL source (restored WSS DB, DMS database) | `db_datareader` (read-only) |
| FileNet | a user who can create documents (and folders, if `create_folders`) in the target classes and object store; the target classes and properties must exist |
| CMIS source | read access to the folders being migrated |
| S3 source | `s3:ListBucket`, `s3:GetObject` (and `s3:ListBucketVersions`, `s3:GetObjectVersion` with versions) |

## Secrets

- `${VAR}` in the config is replaced with environment variables; SQL sources also take
  `password_env` and `password_file` (a Kubernetes / OpenShift Secret mounted as a file wins).
- Credentials are never written to the manifest, the logs or the report.

## TLS

- **SQL Server.** `encrypt = "off" | "optional" | "required"`. The certificate is verified against
  `ca_file` or the operating system's trust store; `hostname_in_certificate` handles a name that
  differs from `host` (for example through a port-forward). `trust_server_certificate = true`
  accepts any certificate: for test systems only. The bundled driver's TLS uses Python's own `ssl`
  module (no pyOpenSSL).
- **FileNet and CMIS.** Verified against the OS trust store, or a PEM bundle with
  `verify_tls = "/path/ca.pem"`. `verify_tls = false` is for test systems only.

## Data at rest

- The manifest holds names, paths, metadata and target ids, never content.
- The `extract` staging area holds plain copies of documents. Put it on a protected volume;
  `verify` deletes each copy once it is verified (`cleanup_staging = true`).
- `local_folder` output is plain files; treat it like the source.

## Supply chain

Every CI install is hash-locked; every GitHub Action is pinned to a commit; CodeQL, OpenSSF
Scorecard and a weekly `pip-audit` of the bundled driver and all tooling run continuously;
releases use PyPI Trusted Publishing with provenance, and Sigstore-signed wheel, sdist and a
CycloneDX SBOM. See {doc}`/getting_started/install` to verify a download, and the repository's
`SECURITY.md` to report a vulnerability.
