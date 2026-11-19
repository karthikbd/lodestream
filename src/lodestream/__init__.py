"""lodestream: bulk content migration from any source into IBM FileNet.

    source (WSS SQL, file share, SQL BLOBs, CSV export, S3, CMIS, or your plugin)
      -> inventory -> filter -> [extract] -> load -> verify   (+ delta for cutover)
      -> sink (FileNet CS GraphQL, local folder, or your plugin)
"""
from .models import DocumentRecord, Status
from .pipeline import Migration
from .registry import register_sink, register_source, register_stage
from .sinks.base import LoadItem, LoadResult, Sink
from .sources.base import Source
from .stages.base import Stage

__version__ = "0.3.1"

__all__ = [
    "DocumentRecord",
    "LoadItem",
    "LoadResult",
    "Migration",
    "Sink",
    "Source",
    "Stage",
    "Status",
    "__version__",
    "register_sink",
    "register_source",
    "register_stage",
]
