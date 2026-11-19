# Security assurance case

Why we believe lodestream meets its security requirements: what it protects, who it trusts, what
can go wrong, and what stops it. It is reviewed before every release (see {doc}`releasing`) and
whenever a source, sink or step is added.

## Security requirements (what users can expect)

1. **Confidentiality of content and credentials.** Documents move only between the source and the sink
   named in the configuration. Credentials are never written to the manifest, logs or reports.
2. **Integrity of what is migrated.** Every document version uploaded is the version that was read,
   byte for byte (SHA-256 recorded on upload, and compared with the extracted copy when `extract` runs), with its metadata, in version order; anything else is
   reported as `FAILED` or `MISMATCH`, never silently accepted.
3. **No surprise connections or code.** No telemetry, no update checks, no runtime dependencies; network
   connections go only to configured endpoints, over TLS with certificate verification by default.
4. **Safe handling of untrusted data.** Document names, paths, metadata and content from the source are
   data, never code, SQL, GraphQL or file-system paths outside the configured folders.
5. **A trustworthy release.** What users install is what was built from the tagged commit: signed,
   reproducible, with a software bill of materials.

## Design and actors

See {doc}`architecture` for the components. Actors and what they can do:

| Actor | Trust | Can |
|---|---|---|
| Operator (writes the configuration, runs the CLI) | Trusted | Choose sources, sinks, queries, credentials, plugins and folders. |
| Source system (SQL Server / WSS, file share, CSV export, S3, CMIS) | Data untrusted, identity verified (TLS) | Supply document names, paths, metadata and content. |
| Target (FileNet Content Services GraphQL) | Identity verified (TLS); responses validated | Accept or reject documents; return identifiers. |
| Network between them | Untrusted | Observe or alter traffic unless TLS is used. |
| Plugins named in `plugins = [...]` | Trusted code, same process | Anything the process can do. |
| Contributors | Reviewed | Propose changes through pull requests with required checks. |
| CI and release pipeline | Trusted, constrained | Build, sign and publish from the repository only. |

## Trust boundaries

1. **Configuration → process.** Unknown keys are rejected; folder templates and steps are validated at
   start-up; secrets come from environment variables or files (`${VAR}`, `password_file`).
2. **Source data → process.** Everything read from a source crosses here: names, paths, metadata values,
   content streams.
3. **Process → target / file system.** GraphQL requests, multipart uploads, staging files, the
   `local_folder` sink, the manifest (SQLite) and reports.
4. **Repository → release.** CI builds and signs; PyPI receives uploads only from the release workflow.

## Threats and countermeasures

| Threat (boundary) | Countermeasure | Evidence |
|---|---|---|
| SQL injection through metadata or partition values (2) | Values are always bound parameters; SQL text comes only from the operator's configuration and fixed fragments | `sources/sql_blob.py`; CodeQL; `ruff S608` reviewed |
| GraphQL injection through names or properties (2→3) | Every value is rendered with `gql_literal` (JSON-escaped); templates are validated against the server's schema by `lodestream check` | `tests/test_check.py`; fuzz target `fuzz_graphql` |
| Path traversal: a document called `../../x` writes outside the staging or output folder (2→3) | Staging names go through `safe_filename`; `local_folder` refuses `..`, separators and drive names in path components and checks the resolved path stays under the root | `tests/test_lodestream.py::test_local_folder_refuses_names_that_escape_the_root` |
| Local file read or SSRF through a URL scheme (`file:`, `ftp:`) in a configured endpoint (1) | The HTTP client accepts only `http` and `https` | `tests/test_config_and_drivers.py::test_http_client_refuses_non_http_urls` |
| Credential disclosure (1, 3) | Secrets from env/files; never logged or stored; reports and manifest hold no credentials; GitHub secret scanning with push protection | {doc}`/user_guide/security` |
| Eavesdropping or tampering in transit (network) | TLS with certificate verification on by default for SQL Server, FileNet, CMIS and S3; `verify_tls = false` and `trust_server_certificate` are opt-in for test systems | `_http.py`, `drivers.py` |
| Corrupted or partial uploads (3) | SHA-256 of every version is computed over the bytes actually uploaded and recorded; with the `extract` step it is also computed on extract and the two must match; `verify` then reads each document back from the target and compares its size; results are recorded per version | `stages/extract.py`, `stages/load.py`, `stages/verify.py` |
| Malformed configuration crashing a long run (1) | Strict validation at start-up (`ConfigError`); fuzzed | `fuzz_config`, `fuzz_mapping` |
| Denial of service by pathological input (2) | Linear-time GraphQL tokenizer; streamed content (bounded memory) | fuzz targets; `tests/test_check.py` |
| Malicious or vulnerable dependency (4) | No runtime dependencies; the bundled driver is pinned, audited by `pip-audit` and declared in the SBOM; CI tooling is hash-locked; actions pinned by SHA; Dependabot | `ci/`, `vulnerability-audit.yml` |
| Tampered release (4) | PyPI Trusted Publishing with provenance; Sigstore-signed assets re-verified by `verify-release.yml`; reproducible builds checked in CI | `python-publish.yml`, `tests.yml` |

## Secure design principles applied

- **Least privilege:** read-only access to sources; documented minimal FileNet rights; CI tokens
  read-only unless a job needs more.
- **Fail-safe defaults:** TLS verification on; unknown configuration keys rejected; failures stop at the
  item, not silently.
- **Complete mediation:** every value crossing boundary 2 is escaped or bound where it is used, not once
  at the edge.
- **Economy of mechanism:** no runtime dependencies; HTTP in one module (`_http.py`), enforced by a test.
- **Open design:** everything above is public and testable; nothing relies on obscurity.
- **Separation of privilege:** publishing needs the protected `release` environment and an OIDC identity,
  not a stored token.
- **Least common mechanism / psychological acceptability:** each step can be run and inspected on its
  own (`--steps`, `--dry-run`, `check`), so safe operation is also the easy path.

## Common weaknesses considered

CWE-89 (SQL injection), CWE-78 and CWE-94 (command and code injection: no `subprocess`, `eval` or
`pickle`), CWE-22 (path traversal), CWE-918 (SSRF), CWE-295 (certificate validation), CWE-312 and
CWE-532 (cleartext or logged secrets), CWE-400 and CWE-1333 (resource and regex DoS), CWE-494 and
CWE-829 (unverified or untrusted code), CWE-20 (input validation). CodeQL and `ruff`'s `S` rules scan
for these on every change; findings must be fixed or justified before merging.

## Review at release

Before each release the maintainer re-reads this page against the changes since the last release
(new inputs, new connections, new files written) and updates it; the release checklist in
{doc}`releasing` includes this step. The last review was for 0.3.1 (November 2026); it found and fixed
the `local_folder` path traversal listed above.
