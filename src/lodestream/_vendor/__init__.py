"""Third-party code bundled inside lodestream so installs never download anything.

* ``pytds`` — python-tds 1.17.1 (MIT, see LICENSE-python-tds.txt), a pure-Python
  implementation of Microsoft's TDS protocol, used to read SQL Server sources (WSS/SharePoint
  content databases, SQL BLOB stores). Imports were rewritten to be package-relative and
  ``tls.py`` was replaced with a standard-library (``ssl``) implementation so encrypted
  connections work without pyOpenSSL. Same modified copy as mssql-ocp-migrate.
"""
