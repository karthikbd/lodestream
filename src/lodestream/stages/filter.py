"""filter: mark PENDING items that should not be migrated as SKIPPED."""
from __future__ import annotations

import fnmatch
from collections import Counter
from typing import Any, Dict, Optional
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..pipeline import Context

from ..models import Status
from ..registry import register_stage
from ..utils import parse_dt, require_dt
from .base import Stage


@register_stage("filter")
class FilterStage(Stage):
    """Marks PENDING items that should not be migrated as SKIPPED (the reason is recorded).

        [[steps]]
        name = "filter"
        versions = "all"                    # all | latest | last_n
        keep_versions = 3                   # for last_n
        exclude_patterns = ["*/forms/*", "*.tmp", "*/_vti_*"]   # matched on lower-case /dir/name
        include_patterns = []               # if set, only matching paths are kept
        min_size = 1
        max_size = 10737418240
        modified_after = "2015-01-01"
        include_content_types = []          # e.g. library names or CMIS types
        exclude_content_types = []
    """

    description = "Skip versions/files you do not want to move (old versions, junk, system files, by date/size/type)."

    def run(self, ctx: "Context", limit: Optional[int] = None) -> Dict[str, Any]:
        o = self.options
        policy = o.get("versions", "all")
        keep_n = {"all": None, "latest": 1}.get(policy, int(o.get("keep_versions", 1)))
        excludes = [p.lower() for p in o.get("exclude_patterns", [])]
        includes = [p.lower() for p in o.get("include_patterns", [])]
        min_size = o.get("min_size")
        max_size = o.get("max_size")
        after = parse_dt(o["modified_after"]) if o.get("modified_after") else None
        inc_types = set(o.get("include_content_types", []))
        exc_types = set(o.get("exclude_content_types", []))
        reasons: Counter[str] = Counter()
        examined = 0
        for page in ctx.manifest.iter_records([Status.PENDING], page=2000):
            tops = ctx.manifest.top_version_indices(list({r.series_id for r in page}), keep_n) if keep_n else {}
            updates = []
            for r in page:
                examined += 1
                path = r.full_path.lower()
                reason = None
                if keep_n and r.version_index not in tops.get(r.series_id, set()):
                    reason = f"version policy {policy}"
                elif any(fnmatch.fnmatchcase(path, p) for p in excludes):
                    reason = "exclude pattern"
                elif includes and not any(fnmatch.fnmatchcase(path, p) for p in includes):
                    reason = "not in include patterns"
                elif min_size is not None and r.size < int(min_size):
                    reason = "below min_size"
                elif max_size is not None and r.size > int(max_size):
                    reason = "above max_size"
                elif after and r.modified and require_dt(r.modified) < after:
                    reason = "older than modified_after"
                elif inc_types and r.content_type not in inc_types:
                    reason = "content type not included"
                elif r.content_type in exc_types:
                    reason = "content type excluded"
                if reason:
                    reasons[reason] += 1
                    updates.append({"source_id": r.source_id, "status": Status.SKIPPED, "error": reason})
            ctx.manifest.update(updates)
        return {"examined": examined, "skipped": sum(reasons.values()), "reasons": dict(reasons),
                "processed": examined}
