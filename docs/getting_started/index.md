# Getting started

```{toctree}
:maxdepth: 1

install
tour
choosing
```

## In one minute

```console
$ pip install lodestream
$ lodestream init wss_to_filenet -o migration.toml     # or fileshare / csv / cmis / s3 / sql
$ lodestream check -c migration.toml                  # prove the source and FileNet work (read-only)
$ lodestream run -c migration.toml --dry-run --rate 300 --gbps 10   # what is there, how long will it take?
$ lodestream run -c migration.toml                     # inventory → filter → extract → load → verify
$ lodestream status -c migration.toml
```

Before the cut-over, pick up what changed since the bulk run:

```console
$ lodestream run -c migration.toml --steps delta,filter,extract,load,verify
```

::::{grid} 1 3 3 3
:gutter: 2

:::{grid-item-card} Installation
:link: install
:link-type: doc
PyPI, offline wheels, corporate repositories, optional drivers.
:::

:::{grid-item-card} 10 minutes to lodestream
:link: tour
:link-type: doc
A complete migration, end to end, with the manifest and the report.
:::

:::{grid-item-card} Choosing a pipeline
:link: choosing
:link-type: doc
Which source, stream or stage, rolling chunks or not: a decision table.
:::
::::
