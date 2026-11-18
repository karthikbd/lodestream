# API reference

This section documents every public interface. The command-line, configuration and plugin pages
are **generated from the code** on each build, and the build fails if a configuration key or a
registered plugin has no description, so they always match the installed version.

```{toctree}
:maxdepth: 2

cli
config
plugins
api
```

| Page | Contents |
|---|---|
| {doc}`cli` | every `lodestream` command and flag |
| {doc}`config` | every top-level and `[mapping]` key with its type, default and meaning |
| {doc}`plugins` | every source, sink and step, with all of its options |
| {doc}`api` | Python classes: `Migration`, `DocumentRecord`, `Source`, `Sink`, `Stage`, the manifest |
