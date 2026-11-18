---
html_theme.sidebar_secondary.remove: true
---

# lodestream documentation

**Date**: Nov 18, 2026 **Version**: {{ version }}

**Download**: [PyPI package](https://pypi.org/project/lodestream/)

**Useful links**:
[Installation](getting_started/install.md) |
[10-minute tour](getting_started/tour.md) |
[WSS / SharePoint](user_guide/wss.md) |
[The 100 TB playbook](user_guide/performance.md) |
[Troubleshooting](user_guide/troubleshooting.md) |
[Release notes](whatsnew/index.md)

**lodestream** is an open source, MIT-licensed Python package for moving documents, with their
versions and metadata, from any content store into **IBM FileNet**. Built-in sources cover WSS /
SharePoint content databases, any SQL database holding files, file shares, CSV exports from any
system, S3 and CMIS repositories, and you can add your own in a few lines. It has no install-time
dependencies (the SQL Server driver is bundled), records every document version in a restartable
manifest, and is built for migrations of 100 TB and more.

::::::{grid} 1 2 2 2
:gutter: 4
:padding: 2 2 0 0
:class-container: sd-text-center

::::{grid-item-card} Getting started
:img-top: _static/index_getting_started.svg
:class-card: intro-card
:shadow: md

New to *lodestream*? The getting started guides cover installation, a complete ten-minute
migration, and how to choose a source and a pipeline.

:::{card-footer}
```{button-ref} getting_started/index
:ref-type: doc
:click-parent:
:color: secondary
:expand:

To the getting started guides
```
:::
::::

::::{grid-item-card} User guide
:img-top: _static/index_user_guide.svg
:class-card: intro-card
:shadow: md

The user guide explains every concept in depth: configuration, sources, the WSS path, the
FileNet sink, the steps, mapping, performance at 100 TB, security and troubleshooting.

:::{card-footer}
```{button-ref} user_guide/index
:ref-type: doc
:click-parent:
:color: secondary
:expand:

To the user guide
```
:::
::::

::::{grid-item-card} API reference
:img-top: _static/index_api.svg
:class-card: intro-card
:shadow: md

The reference describes every command, flag, configuration key, plugin option and Python
class. It's generated from the code, so it always matches the installed version.

:::{card-footer}
```{button-ref} reference/index
:ref-type: doc
:click-parent:
:color: secondary
:expand:

To the reference guide
```
:::
::::

::::{grid-item-card} Developer guide
:img-top: _static/index_contribute.svg
:class-card: intro-card
:shadow: md

Want to add a source, a sink or a step? The developer guide covers the architecture, the
test layers and releasing to PyPI.

:::{card-footer}
```{button-ref} development/index
:ref-type: doc
:click-parent:
:color: secondary
:expand:

To the development guide
```
:::
::::

::::::

```{toctree}
:maxdepth: 3
:hidden:
:titlesonly:

getting_started/index
user_guide/index
reference/index
development/index
whatsnew/index
```
