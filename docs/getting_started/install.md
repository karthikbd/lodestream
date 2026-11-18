# Installation

## Requirements

| | |
|---|---|
| Python | 3.10 or newer (CI runs 3.10, 3.11, 3.12, 3.13). TOML configs need 3.11+; on 3.10 use a JSON config. |
| Operating system | Linux, Windows, macOS: pure Python, one universal wheel (`py3-none-any`) |
| Target | IBM FileNet Content Platform Engine with the Content Services GraphQL API (FileNet 5.5.x or Cloud Pak for Business Automation) |
| Python dependencies | **None.** `pip install` installs this package only. |

## From PyPI

```console
$ pip install lodestream
$ lodestream --version
lodestream {{ version }}
```

This installs the `lodestream` command and the `lodestream` Python package. `python -m lodestream`
works too.

## Windows (PowerShell)

```powershell
# 1. A virtual environment
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install
python -m pip install --upgrade pip
pip install lodestream

# 3. Check
lodestream --version
```

If `Activate.ps1` is blocked, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use
`.\.venv\Scripts\activate.bat` from `cmd`.

## Linux / macOS

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install lodestream
lodestream --version
```

## Offline and air-gapped installs

The package has no dependencies, so a single wheel file is a complete installation. Copy it into the
restricted network and install it without an index:

```console
$ pip download --no-deps lodestream=={{ version }} -d wheels         # on a machine with access
$ pip install --no-index --no-deps wheels/lodestream-{{ version }}-py3-none-any.whl   # on the migration server
```

`--no-index` makes pip refuse any network access, which proves nothing else is fetched.

## Inside a corporate network (JFrog Artifactory / Curation)

If pip goes through Artifactory, point it at your PyPI remote repository:

```powershell
pip install --index-url https://<artifactory-host>/artifactory/api/pypi/<pypi-remote>/simple lodestream
```

or once, for all installs:

```powershell
pip config set global.index-url https://<artifactory-host>/artifactory/api/pypi/<pypi-remote>/simple
```

JFrog Curation evaluates new packages before allowing them. lodestream is easy to approve:

- **One package, nothing else.** It has no runtime dependencies, so Curation evaluates exactly
  one package.
- **MIT-licensed**, published from GitHub with **PyPI Trusted Publishing**. Every file on PyPI has a
  **provenance attestation** linking it to the GitHub workflow run that built it.
- **Signed releases.** GitHub release assets are signed with **Sigstore** and come with a
  **CycloneDX SBOM**. The SBOM declares the bundled third-party code (python-tds 1.17.1, MIT), which
  scanners that read package metadata would otherwise not see.
- **Continuous checks:** OpenSSF Scorecard, CodeQL, and a weekly `pip-audit` of the bundled driver
  and all build tooling.

A very new version can be held by a "package age" policy for some days. That's a policy wait, not
a problem with the package.

To check a downloaded file's signature against the GitHub workflow that produced it:

```console
$ pip download --no-deps lodestream=={{ version }} -d dl
$ gh release download v{{ version }} -R karthikbd/lodestream -p "lodestream-{{ version }}-py3-none-any.whl.sigstore.json" -D dl
$ python -m pip install sigstore
$ python -m sigstore verify github dl/lodestream-{{ version }}-py3-none-any.whl \
    --bundle dl/lodestream-{{ version }}-py3-none-any.whl.sigstore.json \
    --cert-identity https://github.com/karthikbd/lodestream/.github/workflows/python-publish.yml@refs/tags/v{{ version }} \
    --repository karthikbd/lodestream --ref refs/tags/v{{ version }} --trigger release
OK: dl/lodestream-{{ version }}-py3-none-any.whl
```

The `.sigstore.json` bundles for the wheel, the sdist and the SBOM are attached to the GitHub
release (download them from the release page if you don't have the `gh` CLI). Behind a proxy that
blocks Sigstore's update server (`tuf-repo-cdn.sigstore.dev`), add `--offline`: the check then uses
the trust root shipped inside the `sigstore` package and still verifies the signature, the
certificate chain and the transparency-log inclusion proof in the bundle.

The same check runs on GitHub after every release (`verify-release.yml`): it downloads the release
files, verifies each signature against the publish workflow and the tag, and confirms PyPI serves
byte-identical files.

## Optional modules

lodestream never installs these; it uses them only if they are already installed:

| Module | Used for |
|---|---|
| `pyodbc` + Microsoft ODBC Driver 18 | SQL Server sources (`wss_sql`, `sql_blob`) when `driver = "auto"` finds them; the bundled driver is used otherwise |
| `boto3` | the `s3` source |
| `PyYAML` | `.yaml` config files (TOML and JSON need nothing) |

## Building the documentation

```console
$ pip install -e ".[docs]"
$ python -m sphinx -b html docs docs/_build/html
```
