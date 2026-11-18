# Third-party code bundled in lodestream

## python-tds 1.17.1 — `src/lodestream/_vendor/pytds/`
- Upstream: https://github.com/denisenkom/pytds — MIT License (`_vendor/LICENSE-python-tds.txt`)
- The same modified copy as in mssql-ocp-migrate. Modifications:
  - absolute `pytds` imports rewritten to `lodestream._vendor.pytds` (no clash with an installed pytds)
  - `tls.py` re-implemented on the standard-library `ssl` module (MemoryBIO/SSLObject) instead of pyOpenSSL
  - `connect()` gained a `tls_server_hostname` argument (certificate host-name override)
