# Configuration reference

Every key accepted at the top level of the configuration file and in `[mapping]`, generated from
`lodestream.config`. Unknown keys are rejected. Each source, sink and step has its own options,
listed in {doc}`plugins`. TOML example:

```toml
manifest = "./state/manifest.db"
steps = ["inventory", "filter", "load", "verify"]

[source]
type = "filesystem"
options = { root = "/mnt/share" }

[sink]
type = "filenet_graphql"
options = { endpoint = "https://cpe.example.com/content-services-graphql/graphql", repository = "OS1" }

[mapping]
default_class = "Document"
```

The same structure works in JSON (`{"source": {...}, "sink": {...}, "mapping": {...}}`), and in
YAML if PyYAML is installed. `${VAR}` and `${VAR:-default}` are replaced with environment variables
anywhere in the file.

```{include} _generated/config_table.md
```
