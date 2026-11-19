# Roadmap

What we plan for the next 12 months (December 2026 to November 2027). Plans change; issues and pull
requests that move these forward are welcome, and each item will get its own issue when work starts.

## Project health

- **A second maintainer** (ideally from another organization), so changes get a second reviewer, releases
  don't depend on one person, and the project can reach the OpenSSF Best Practices **gold** level and
  **baseline level 3** (non-author approval on every merge).
- **Coverage**: raise statement coverage from about 87% to 90% and branch coverage to 80% (gold levels).
- **Copyright and SPDX license lines** in every source file.
- Mark issues suitable for new contributors with the `good first issue` label.

## Migrations

- **FileNet pilot feedback**: tune the GraphQL templates against more FileNet / Cloud Pak for Business
  Automation releases, and document the differences found.
- **Sources**: SharePoint Online / Microsoft 365 (Graph API), Documentum REST, file shares with NTFS
  ACL capture.
- **Security metadata**: carry source permissions (ACLs) through mapping to FileNet security templates.
- **Throughput**: per-partition rate limiting and adaptive batch sizes for the `load` step.
- **Reporting**: a reconciliation report per partition that can be signed off by the business.

## Releases

About one minor release per quarter, patch releases as needed (see [SECURITY.md](SECURITY.md) for which
versions receive fixes). Every release is signed, reproducible and listed in [CHANGELOG.md](CHANGELOG.md).
