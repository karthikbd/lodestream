# Python API

Everything the command line does goes through {class}`~lodestream.pipeline.Migration`.

```python
from lodestream import Migration

m = Migration.from_file("migration.toml")
m.run(steps=["inventory", "filter"])
print(m.estimate(docs_per_sec=300, link_gbps=10))
Migration.from_file("migration.toml").run()       # the configured plan
```

## Running a migration

```{eval-rst}
.. autoclass:: lodestream.pipeline.Migration
   :members: from_file, run, plan, status, estimate, available_steps

.. autoclass:: lodestream.pipeline.Context
   :members: source, sink, open_sink, path
```

## Records and statuses

```{eval-rst}
.. autoclass:: lodestream.models.DocumentRecord
   :members: full_path, builtin_fields

.. autoclass:: lodestream.models.Status
   :members:
   :undoc-members:
```

## Writing plugins

See {doc}`/user_guide/plugins` for complete examples.

```{eval-rst}
.. autoclass:: lodestream.sources.base.Source
   :members: partitions, iter_documents, open_content, close

.. autoclass:: lodestream.sinks.base.Sink
   :members: open, load_batch, verify, close

.. autoclass:: lodestream.sinks.base.LoadItem
   :members: open, mime

.. autoclass:: lodestream.sinks.base.LoadResult

.. autoclass:: lodestream.stages.base.Stage
   :members: run

.. autofunction:: lodestream.registry.register_source
.. autofunction:: lodestream.registry.register_sink
.. autofunction:: lodestream.registry.register_stage
```

## The manifest

```{eval-rst}
.. autoclass:: lodestream.manifest.Manifest
   :members: add_records, update, iter_records, iter_series, series_records, get, counts, partition_counts, reset_failed, runs, last_run
```

## Configuration and connections

```{eval-rst}
.. autofunction:: lodestream.config.load_config

.. autoexception:: lodestream.config.ConfigError

.. autoclass:: lodestream.mapping.Mapper
   :members: map

.. autofunction:: lodestream.drivers.connect

.. autofunction:: lodestream.drivers.choose_driver
```
