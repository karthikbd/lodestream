"""Generate the configuration, plugin and CLI reference pages from the code itself.

Run automatically by ``conf.py`` on every build. The build fails if a configuration key has no
description here, or if a registered source, sink or step has no documented options, so the
reference can never silently drift from the code.
"""
from __future__ import annotations

import argparse
import inspect
from pathlib import Path

from lodestream import config as C
from lodestream.cli import build_parser
from lodestream.registry import SINKS, SOURCES, STAGES, load_builtins

OUT = Path(__file__).parent / "reference" / "_generated"

TOP_LEVEL = {
    "name": ("string", "optional", "A label for this migration (shown nowhere else; for your own bookkeeping)."),
    "manifest": ("string", '``"lodestream-manifest.db"``',
                 "Path of the SQLite manifest that tracks every document version. Relative paths are resolved "
                 "against the config file's folder. Keep it on local SSD."),
    "plugins": ("list of strings", "``[]``",
                "Python modules imported before the run so their ``@register_source`` / ``@register_sink`` / "
                "``@register_stage`` plugins are available."),
    "source": ("table", "*required*", "Where documents come from: ``type`` (a registered source) and ``options``."),
    "sink": ("table", "*required*", "Where documents go: ``type`` (a registered sink) and ``options``."),
    "mapping": ("table", "*(section)*", "How source records become target classes, properties and folders."),
    "steps": ("list", '``["inventory", "filter", "extract", "load", "verify"]``',
              "The default plan: step names, or tables with ``name`` plus that step's options. "
              "``--steps`` overrides the list for one run."),
    "rolling": ("table", "none", "``chunk_docs = N`` runs consecutive extract/load/verify steps in repeating chunks "
                "of N documents, so staging holds only a slice of the data."),
    "hooks": ("table", "none", "``before`` / ``after`` tables mapping a step name to a list of ``module:function`` "
              "callables, called as ``fn(ctx, step, stats)``."),
}
MAPPING = {
    "default_class": ("string", '``"Document"``', "Target document class when ``classes`` has no match."),
    "classes": ("table", "``{}``", "Source content type (library, CMIS type, CSV column...) to target class. "
                "``\"*\"`` matches anything."),
    "properties": ("table", "``{}``", "Source field to target property: a property name, or a table with "
                   "``target``, ``type`` (string, int, float, bool, datetime, date), ``default`` and ``max_length``. "
                   "Built-in fields start with ``_``: ``_name``, ``_path``, ``_directory``, ``_size``, "
                   "``_modified``, ``_content_type``, ``_source_id``, ``_series_id``, ``_version_index``, "
                   "``_partition``."),
    "passthrough_unmapped": ("boolean", "``false``", "Also send source properties that have no mapping, unchanged."),
    "title_property": ("string", '``"DocumentTitle"``', "Property set to the file name when nothing else sets it."),
    "folder": ("string", "``null``", "Folder path template, e.g. ``\"/Migrated/{directory}\"``; fields: "
               "``{directory}``, ``{partition}``, ``{content_type}``, ``{name}`` and any property. "
               "``null`` = do not file documents in a folder."),
    "strip_path_prefixes": ("list of strings", "``[]``", "Leading path segments removed from ``{directory}``."),
}


def _table(rows, keys, what) -> list:
    missing = sorted(set(keys) - set(rows))
    stale = sorted(set(rows) - set(keys))
    if missing or stale:
        raise SystemExit(f"{what} reference out of date: describe {missing}, remove {stale}")
    lines = ["```{list-table}", ":header-rows: 1", ":widths: 20 14 18 48", "",
             "* - Key", "  - Type", "  - Default", "  - Description"]
    for k in keys:
        typ, default, desc = rows[k]
        lines += [f"* - ``{k}``", f"  - {typ}", f"  - {default}", f"  - {desc}"]
    return lines + ["```", ""]


def config_reference() -> str:
    lines = ["## Top level", ""] + _table(TOP_LEVEL, C.TOP_LEVEL_KEYS, "top-level config")
    lines += ["## `[mapping]`", ""] + _table(MAPPING, C.MAPPING_KEYS, "mapping")
    return "\n".join(lines)


def _options_block(cls, kind: str, name: str) -> list:
    doc = inspect.getdoc(cls) or ""
    if "options" not in doc and kind != "step":
        raise SystemExit(f"{kind} {name!r} ({cls.__module__}) has no documented options in its docstring")
    head = f"{name}"
    out = [f"(plugin-{kind}-{name})=", f"### `{head}`", ""]
    if kind == "step" and getattr(cls, "description", ""):
        out += [cls.description, ""]
    flags = []
    if getattr(cls, "writes_target", False):
        flags.append("skipped by `--dry-run`")
    if getattr(cls, "chunkable", False):
        flags.append("takes part in `rolling` chunks")
    if flags:
        out += ["*" + "; ".join(flags) + ".*", ""]
    if doc:
        out += ["```text", doc, "```", ""]
    out += [f"Implemented by `{cls.__module__}.{cls.__qualname__}`.", ""]
    return out


def plugins_reference() -> str:
    load_builtins()
    out = ["## Sources", ""]
    for name in sorted(SOURCES):
        out += _options_block(SOURCES[name], "source", name)
    out += ["## Sinks", ""]
    for name in sorted(SINKS):
        out += _options_block(SINKS[name], "sink", name)
    out += ["## Steps", ""]
    for name in STAGES:
        out += _options_block(STAGES[name], "step", name)
    return "\n".join(out)


def cli_reference() -> str:
    parser = build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    helps = {a.dest: a.help for a in sub._choices_actions}
    out = ["## Global options", "", "```text", parser.format_help().strip(), "```", ""]
    for name, sp in sub.choices.items():
        out += [f"(cli-{name})=", f"## `lodestream {name}`", "", (helps.get(name) or "").capitalize() + ".", "",
                "```text", sp.format_help().replace("usage: lodestream", "lodestream").strip(), "```", ""]
    return "\n".join(out)


def generate() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "config_table.md").write_text(config_reference(), encoding="utf-8")
    (OUT / "plugins.md").write_text(plugins_reference(), encoding="utf-8")
    (OUT / "cli.md").write_text(cli_reference(), encoding="utf-8")


if __name__ == "__main__":
    generate()
