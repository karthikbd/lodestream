# Contributing to lodestream

Thanks for helping. Bug reports, documentation fixes, new sources and sinks are all welcome.

## Reporting bugs and asking questions

- **Bugs and feature requests:** open a [GitHub issue](https://github.com/karthikbd/lodestream/issues).
  Include the lodestream version (`lodestream --version`), Python version, the source and sink types,
  the command you ran, and the output of `lodestream check -c <config>` if it is relevant. Remove
  host names, credentials and document names you can't share.
- **Security vulnerabilities:** do **not** open a public issue. Report them privately as described in
  [SECURITY.md](SECURITY.md).

The maintainer aims to respond to new issues within 7 days.

## Making a change

1. Open an issue first for anything larger than a small fix, so the approach can be agreed.
2. Fork the repository and create a branch from `main`.
3. Set up a development environment:

   ```console
   $ python -m venv .venv && . .venv/bin/activate
   $ pip install --require-hashes -r ci/requirements-test.txt
   $ pip install --no-deps -e .
   ```

4. Make the change, **with tests** (see below), and update the documentation in `docs/` and
   `CHANGELOG.md` when behaviour changes.
5. Run the checks CI runs:

   ```console
   $ ruff check src tests          # lint: must be clean
   $ mypy src                      # types: must be clean
   $ pytest -q                     # unit, pipeline and over-the-wire HTTP tests
   $ python -m sphinx -W -b html docs docs/_build/html   # docs: warnings are errors
   ```

6. Open a pull request against `main`. CI runs the tests on Python 3.10–3.13, the end-to-end suite
   against SQL Server (bundled driver and pyodbc), an S3 server and Alfresco (CMIS), CodeQL, a
   vulnerability audit and ClusterFuzzLite fuzzing. All of them must pass.

## Rules for code

- **No runtime dependencies.** lodestream must install and run with the Python standard library and
  its bundled code only. A third-party module may be used *only if already installed* (imported
  inside a function, with a clear error when missing). `tests/test_no_downloads.py` enforces this.
- **No network access except to configured systems.** Only `src/lodestream/_http.py` may speak HTTP,
  and only the FileNet sink and CMIS source may use it.
- **Tests are required.** New functionality needs tests that would fail without it; bug fixes need a
  regression test. Code that talks to an external system needs a test against an in-process stand-in
  (see `tests/fakes.py`) and, where practical, an end-to-end test in `tests/e2e`.
- **Inputs from sources and configs are untrusted.** Parsing code should have a fuzz target in
  `tests/fuzz` (Atheris).
- **Style:** `ruff` and `mypy` clean; type hints on public functions; docstrings on plugins, because
  the reference documentation is generated from them.
- **CI tooling is hash-locked.** To change a tool version, edit `ci/requirements-*.in` and regenerate
  the `.txt` file with `uv pip compile --universal --generate-hashes` (see `docs/development/testing.md`).
  GitHub Actions are pinned by commit SHA.

## Licensing of contributions

lodestream is MIT-licensed. By submitting a pull request you agree that your contribution is licensed
under the same [MIT License](LICENSE), and you confirm you have the right to submit it. Code copied
from other projects must have a compatible license and be recorded in `THIRD_PARTY_NOTICES.md`.

## Releases

Releases follow [semantic versioning](https://semver.org/) and are described in `CHANGELOG.md` and
`docs/whatsnew/index.md`. See `docs/development/releasing.md` for the release process.
