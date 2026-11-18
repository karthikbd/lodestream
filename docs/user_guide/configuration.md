# Configuration

A migration is described by one file. **TOML** is the default (read with Python's own `tomllib`,
Python 3.11+); **JSON** works on every Python version; **YAML** works only if PyYAML is already
installed. `lodestream init <template>` writes a commented starting point.

## Structure

```toml
name = "wss-to-filenet"               # optional label
manifest = "./state/manifest.db"      # the run's state; relative paths start at the config's folder
plugins = ["mycompany.lodestream_ext"]  # optional: modules with your own sources/sinks/steps

[source]                              # where documents come from
type = "wss_sql"
[source.options]
host = "sqlstage01"
# ...

[sink]                                # where they go
type = "filenet_graphql"
[sink.options]
endpoint = "https://cpe.example.com/content-services-graphql/graphql"
# ...

[mapping]                             # classes, properties, folders (see the Mapping page)
default_class = "Document"

[[steps]]                             # the default plan, in order
name = "inventory"
workers = 8
[[steps]]
name = "load"
workers = 32

[rolling]                             # optional
chunk_docs = 200000

[hooks]                               # optional: your functions around steps
before = { load = ["my_admin:disable_cbr"] }
```

`steps` can also be a plain list, `steps = ["inventory", "filter", "load", "verify"]`, when the
defaults are fine. Unknown top-level or `[mapping]` keys are rejected, so a typo fails at once.
The full key list is in {doc}`/reference/config`; each source, sink and step's options are in
{doc}`/reference/plugins`.

## Secrets

Never write passwords into the file:

- `${VAR}` anywhere in the file is replaced with the environment variable `VAR`;
  `${VAR:-default}` supplies a default. Use it for FileNet and CMIS credentials.
- SQL sources also accept `password_env = "VAR"` and `password_file = "/path"`. The file wins
  over the variable, which makes OpenShift / Kubernetes Secrets mounted as files the simplest
  option.

## Overriding the plan for one run

```console
$ lodestream run -c migration.toml --steps inventory,filter          # scope first
$ lodestream run -c migration.toml --steps extract,load,verify       # bulk move
$ lodestream run -c migration.toml --steps delta,filter,load,verify  # catch-up before cut-over
```

`--steps` uses the options from the config for each named step. A step that isn't in the config
runs with its defaults.

## Hooks

Hooks call your own Python functions before or after a step, with the signature
`fn(ctx, step, stats)` (`stats` is `None` before the step). Typical uses: switch off FileNet
content-based retrieval and subscriptions before `load`, switch them back on after `verify`,
post progress to a chat channel.

```toml
[hooks]
before = { load = ["my_fn_admin:pause_cbr"] }
after = { verify = ["my_fn_admin:resume_cbr", "my_fn_admin:notify_team"] }
```

## Python instead of a file

```python
from lodestream import Migration

m = Migration({"manifest": "m.db",
               "source": {"type": "filesystem", "options": {"root": "/mnt/share"}},
               "sink": {"type": "local_folder", "options": {"root": "./out"}},
               "steps": ["inventory", "load", "verify"]}, base_dir=".")
m.run()
print(m.status())
```
