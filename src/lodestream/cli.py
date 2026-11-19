"""Command line interface:  lodestream <command> -c migration.yaml"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys

from . import __version__
from .pipeline import Migration
from .registry import SINKS, SOURCES, load_builtins
from .utils import human_bytes

_EXAMPLES = os.path.join(os.path.dirname(__file__), "examples")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")


def cmd_steps(args) -> int:
    load_builtins()
    if args.config:
        Migration.from_file(args.config)  # loads plugins declared in the config
    print("Steps (run any subset, in any order, with --steps):")
    for name, desc in Migration.available_steps().items():
        print(f"  {name:<10} {desc}")
    print("\nSources:", ", ".join(sorted(SOURCES)))
    print("Sinks:  ", ", ".join(sorted(SINKS)))
    return 0


def cmd_run(args) -> int:
    m = Migration.from_file(args.config)
    steps = [s.strip() for s in args.steps.split(",")] if args.steps else None
    results = m.run(steps=steps, dry_run=args.dry_run)
    print(json.dumps(results, indent=2, default=str))
    if args.dry_run:
        print(json.dumps(Migration.from_file(args.config).estimate(args.rate, args.gbps), indent=2))
    failed = sum(r.get("failed", 0) for r in results)
    return 2 if failed else 0


_MARK = {"ok": "OK  ", "warn": "WARN", "skip": "SKIP", "fail": "FAIL"}


def cmd_check(args) -> int:
    results = Migration.from_file(args.config).check(sample=args.sample)
    if args.json:
        print(json.dumps([r.__dict__ for r in results], indent=2))
    else:
        for r in results:
            print(f"[{_MARK[r.status]}] {r.area:<7} {r.name}" + (f"\n         {r.detail}" if r.detail else ""))
        failed = sum(r.status == "fail" for r in results)
        warned = sum(r.status == "warn" for r in results)
        print(f"\n{len(results) - failed - warned} passed, {warned} warning(s), {failed} failed")
    return 1 if any(r.status == "fail" for r in results) else 0


def cmd_status(args) -> int:
    st = Migration.from_file(args.config).status()
    if args.json:
        print(json.dumps(st, indent=2, default=str))
        return 0
    print(f"Total documents/versions: {st['total_docs']:,}")
    for status, v in st["by_status"].items():
        print(f"  {status:<10} {v['count']:>14,}  {human_bytes(v['bytes']):>12}")
    print("\nRecent runs:")
    for r in st["recent_runs"]:
        s = r["stats"]
        keys = ("new", "skipped", "extracted", "loaded", "verified", "failed", "mismatch", "docs_per_sec")
        summary = ", ".join(f"{k}={s[k]}" for k in keys if k in s)
        print(f"  #{r['run_id']:<4} {r['step']:<10} {r['started']}  {summary}")
    return 0


def cmd_estimate(args) -> int:
    print(json.dumps(Migration.from_file(args.config).estimate(args.rate, args.gbps), indent=2))
    return 0


def cmd_retry(args) -> int:
    n = Migration.from_file(args.config).manifest.reset_failed(reset_attempts=not args.keep_attempts)
    print(f"Reset {n:,} FAILED item(s); run `lodestream run` (load step) to retry them.")
    return 0


def cmd_init(args) -> int:
    src = os.path.join(_EXAMPLES, f"{args.template}.toml")
    if not os.path.exists(src):
        choices = sorted(f[:-5] for f in os.listdir(_EXAMPLES) if f.endswith(".toml"))
        print(f"Unknown template {args.template!r}. Choose from: {', '.join(choices)}")
        return 1
    if os.path.exists(args.output) and not args.force:
        print(f"{args.output} exists (use --force to overwrite)")
        return 1
    shutil.copyfile(src, args.output)
    print(f"Wrote {args.output} from template '{args.template}'. Edit it, then: lodestream run -c {args.output}")
    return 0


TEMPLATES = ("wss_to_filenet", "fileshare_to_filenet", "csv_to_filenet", "cmis_to_filenet",
             "s3_to_filenet", "sql_to_filenet")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lodestream", description="Bulk content migration from any source into IBM FileNet.")
    p.add_argument("--version", action="version", version=f"lodestream {__version__}")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="write a starter config from a template")
    s.add_argument("template", nargs="?", default="wss_to_filenet", choices=TEMPLATES,
                   help="starter template (default: wss_to_filenet)")
    s.add_argument("-o", "--output", default="migration.toml")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("steps", help="list available steps, sources and sinks")
    s.add_argument("-c", "--config", help="also list plugins declared in this config")
    s.set_defaults(func=cmd_steps)

    s = sub.add_parser("check", help="pre-flight: prove the source and target work, read-only")
    s.add_argument("-c", "--config", required=True, help="config file: .toml, .json, or .yaml if PyYAML is installed")
    s.add_argument("--sample", type=int, default=5, help="sample records to read per query (default 5)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("run", help="run the migration (all configured steps or --steps)")
    s.add_argument("-c", "--config", required=True, help="config file: .toml, .json, or .yaml if PyYAML is installed")
    s.add_argument("--steps", help="comma-separated, e.g. inventory,filter  or  delta,load,verify")
    s.add_argument("--dry-run", action="store_true", help="inventory/filter only, then estimate")
    s.add_argument("--rate", type=float, help="docs/sec for the estimate (dry run)")
    s.add_argument("--gbps", type=float, help="network link speed for the estimate (dry run)")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("status", help="counts by status and recent runs")
    s.add_argument("-c", "--config", required=True, help="config file: .toml, .json, or .yaml if PyYAML is installed")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("estimate", help="time remaining at observed or given rate")
    s.add_argument("-c", "--config", required=True, help="config file: .toml, .json, or .yaml if PyYAML is installed")
    s.add_argument("--rate", type=float)
    s.add_argument("--gbps", type=float)
    s.set_defaults(func=cmd_estimate)

    s = sub.add_parser("retry", help="send FAILED items back to the queue")
    s.add_argument("-c", "--config", required=True, help="config file: .toml, .json, or .yaml if PyYAML is installed")
    s.add_argument("--keep-attempts", action="store_true")
    s.set_defaults(func=cmd_retry)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    try:
        return args.func(args)
    except BrokenPipeError:  # e.g. `lodestream status ... | head`
        sys.stderr.close()
        return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
