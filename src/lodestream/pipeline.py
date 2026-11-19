"""Migration orchestrator: picks steps dynamically and runs them."""
from __future__ import annotations

import os
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .checks import CheckContext, CheckResult, run as run_check
from .config import TOP_LEVEL_KEYS, check_keys, load_config, normalize_steps
from .manifest import Manifest
from .mapping import Mapper
from .models import Status
from .registry import SINKS, SOURCES, STAGES, load_builtins
from .stages.base import Stage
from .utils import human_bytes, human_duration, import_object, log


class Context:
    """What every step receives."""

    def __init__(self, migration: "Migration", step_names: Sequence[str], dry_run: bool):
        self.migration = migration
        self.config = migration.config
        self.manifest = migration.manifest
        self.mapper = migration.mapper
        self.step_names = list(step_names)
        self.dry_run = dry_run
        self.stop_event = migration.stop_event

    @property
    def source(self):
        return self.migration.source

    @property
    def sink(self):
        return self.migration.sink

    def open_sink(self) -> None:
        self.migration.open_sink()

    def path(self, p: str) -> str:
        return self.migration.path(p)


class Migration:
    """A configured migration: the programmatic entry point.

    Example::

        from lodestream import Migration
        m = Migration.from_file("migration.toml")
        m.run()                                  # steps from the config
        m.run(steps=["delta", "load", "verify"]) # or choose steps dynamically

    ``config`` is the parsed configuration; relative paths in it are resolved against ``base_dir``.
    """

    def __init__(self, config: Dict[str, Any], base_dir: str = "."):
        load_builtins()
        check_keys(config, TOP_LEVEL_KEYS, "the config file")
        self.config = config
        self.base_dir = os.path.abspath(base_dir)
        for plugin in config.get("plugins", []) or []:
            __import__(plugin)
        manifest_path = self.path(config.get("manifest", "lodestream-manifest.db"))
        os.makedirs(os.path.dirname(manifest_path) or ".", exist_ok=True)
        self.manifest = Manifest(manifest_path)
        self.mapper = Mapper(config.get("mapping"))
        self.steps_config = normalize_steps(config.get("steps"))
        self.stop_event = threading.Event()
        self._source = None
        self._sink = None
        self._sink_open = False
        self._sink_lock = threading.Lock()

    @classmethod
    def from_file(cls, path: str) -> "Migration":
        return cls(load_config(path), os.path.dirname(os.path.abspath(path)))

    def path(self, p: str) -> str:
        return os.path.normpath(p if os.path.isabs(p) else os.path.join(self.base_dir, p))

    # ------------------------------------------------------------ plugins
    @staticmethod
    def _build(table, spec: Dict[str, Any], kind: str, base_dir: str):
        if not spec or "type" not in spec:
            raise ValueError(f"Config needs a `{kind}` section with a `type`")
        if spec["type"] not in table:
            raise ValueError(f"Unknown {kind} type {spec['type']!r}. Available: {', '.join(sorted(table))}")
        return table[spec["type"]](spec.get("options") or {}, base_dir)

    @property
    def source(self):
        if self._source is None:
            self._source = self._build(SOURCES, self.config.get("source"), "source", self.base_dir)
        return self._source

    @property
    def sink(self):
        if self._sink is None:
            self._sink = self._build(SINKS, self.config.get("sink"), "sink", self.base_dir)
        return self._sink

    def open_sink(self) -> None:
        with self._sink_lock:
            if not self._sink_open:
                self.sink.open()
                self._sink_open = True

    def close(self) -> None:
        if self._source is not None:
            self._source.close()
        if self._sink is not None and self._sink_open:
            self._sink.close()
            self._sink_open = False

    # ------------------------------------------------------------ planning
    @staticmethod
    def available_steps() -> Dict[str, str]:
        load_builtins()
        return {name: cls.description for name, cls in STAGES.items()}

    def plan(self, steps: Optional[Sequence[str]] = None) -> List[Tuple[str, Stage]]:
        configured = {name: opts for name, opts in self.steps_config}
        names = list(steps) if steps else [n for n, o in self.steps_config if o.get("enabled", True)]
        unknown = [n for n in names if n not in STAGES]
        if unknown:
            raise ValueError(f"Unknown step(s) {unknown}. Available: {', '.join(STAGES)}")
        return [(n, STAGES[n]({k: v for k, v in configured.get(n, {}).items() if k != "enabled"}))
                for n in names]

    # ------------------------------------------------------------ running
    def _hooks(self, when: str, step: str) -> List:
        names = ((self.config.get("hooks") or {}).get(when) or {}).get(step) or []
        return [import_object(n) for n in names]

    def _run_stage(self, ctx: Context, name: str, stage: Stage, limit: Optional[int] = None,
                   chunk: Optional[int] = None) -> Dict[str, Any]:
        if ctx.dry_run and stage.writes_target:
            log.info("[%s] skipped (dry run)", name)
            return {"step": name, "skipped": "dry-run", "processed": 0}
        for hook in self._hooks("before", name):
            hook(ctx, name, None)
        label = f"{name} (chunk {chunk})" if chunk else name
        log.info("[%s] starting", label)
        run_id = self.manifest.start_run(name)
        stats = {"step": name, **(stage.run(ctx, limit=limit) or {})}
        if chunk:
            stats["chunk"] = chunk
        self.manifest.finish_run(run_id, stats)
        for hook in self._hooks("after", name):
            hook(ctx, name, stats)
        log.info("[%s] done: %s", label, {k: v for k, v in stats.items() if k != "step"})
        return stats

    def run(self, steps: Optional[Sequence[str]] = None, dry_run: bool = False) -> List[Dict[str, Any]]:
        plan = self.plan(steps)
        ctx = Context(self, [n for n, _ in plan], dry_run)
        chunk_docs = (self.config.get("rolling") or {}).get("chunk_docs")
        results: List[Dict[str, Any]] = []
        log.info("Plan: %s%s", " -> ".join(n for n, _ in plan),
                 f" (rolling chunks of {int(chunk_docs):,} docs)" if chunk_docs else "")
        try:
            i = 0
            while i < len(plan) and not self.stop_event.is_set():
                name, stage = plan[i]
                if chunk_docs and stage.chunkable and not dry_run:
                    group = []
                    while i < len(plan) and plan[i][1].chunkable:
                        group.append(plan[i])
                        i += 1
                    chunk = 0
                    while not self.stop_event.is_set():
                        chunk += 1
                        did = 0
                        for gname, gstage in group:
                            st = self._run_stage(ctx, gname, gstage, limit=int(chunk_docs), chunk=chunk)
                            results.append(st)
                            did += st.get("processed", 0)
                        if not did:
                            break
                else:
                    results.append(self._run_stage(ctx, name, stage))
                    i += 1
        except KeyboardInterrupt:
            self.stop_event.set()
            log.warning("Interrupted: stopping after in-flight work; rerun to resume.")
        finally:
            self.close()
        return results

    # ------------------------------------------------------------ pre-flight
    def check(self, sample: int = 5) -> List[CheckResult]:
        """Read-only pre-flight checks against the real source and target: connections, schemas,
        sample records, one content read, and (FileNet) GraphQL operations, object store, classes
        and properties. Nothing is written to the source, the target or the manifest."""
        results: List[CheckResult] = []
        results.append(run_check("config", "steps", lambda: " -> ".join(n for n, _ in self.plan())))
        targets = [s["target"] for s in self.mapper.properties.values()]
        if self.mapper.title_property:
            targets.append(self.mapper.title_property)
        classes = sorted({*self.mapper.classes.values(), self.mapper.default_class})
        cc = CheckContext(sample=sample, classes={c: sorted(set(targets)) for c in classes})
        try:
            try:
                source = self.source
            except Exception as exc:  # noqa: BLE001
                results.append(CheckResult("source", "configure source", "fail", f"{type(exc).__name__}: {exc}"))
            else:
                results.extend(source.check(cc))
            try:
                sink = self.sink
            except Exception as exc:  # noqa: BLE001
                results.append(CheckResult("sink", "configure sink", "fail", f"{type(exc).__name__}: {exc}"))
            else:
                results.extend(sink.check(cc))
                self._sink_open = True
        finally:
            self.close()
        return results

    # ------------------------------------------------------------ reporting
    def status(self) -> Dict[str, Any]:
        counts = self.manifest.counts()
        total = sum(c for c, _ in counts.values())
        return {"total_docs": total,
                "by_status": {k: {"count": c, "bytes": b} for k, (c, b) in sorted(counts.items())},
                "recent_runs": self.manifest.runs(10)}

    def estimate(self, docs_per_sec: Optional[float] = None, link_gbps: Optional[float] = None) -> Dict[str, Any]:
        counts = self.manifest.counts()
        remaining = sum(counts.get(s.value, (0, 0))[0] for s in (Status.PENDING, Status.EXTRACTED, Status.FAILED))
        remaining_bytes = sum(counts.get(s.value, (0, 0))[1] for s in (Status.PENDING, Status.EXTRACTED, Status.FAILED))
        observed = None
        last = self.manifest.last_run(["load"])
        if last and last["stats"].get("docs_per_sec"):
            observed = float(last["stats"]["docs_per_sec"])
        rate = docs_per_sec or observed
        out = {"remaining_docs": remaining, "remaining_bytes": remaining_bytes,
               "remaining_human": human_bytes(remaining_bytes),
               "rate_docs_per_sec": rate, "rate_source": "given" if docs_per_sec else ("observed" if observed else None)}
        if rate:
            out["load_time"] = human_duration(remaining / rate)
        if link_gbps:
            out["network_time_at_full_link"] = human_duration(remaining_bytes * 8 / (link_gbps * 1e9))
        return out
