# Command-line reference

The `lodestream` command is installed with the package. You can also run it as
`python -m lodestream`.

## Commands at a glance

| Command | Purpose |
|---|---|
| [`init`](#cli-init) | write a commented starter configuration from a template |
| [`steps`](#cli-steps) | list the available steps, sources and sinks |
| [`run`](#cli-run) | run the configured steps, or the ones given with `--steps`; `--dry-run` to count and estimate |
| [`status`](#cli-status) | counts by status and recent runs |
| [`estimate`](#cli-estimate) | time left at the measured or a given rate |
| [`retry`](#cli-retry) | send `FAILED` items back to the queue |

Exit codes: `0` success, `2` when a run finished with failed items, `1` for usage errors.

```{include} _generated/cli.md
```
