"""List all indexed doc repos."""

import time
from typing import Optional

from ..storage import DocStore


def list_repos(storage_path: Optional[str] = None) -> dict:
    """List all indexed documentation repositories."""
    t0 = time.perf_counter()
    store = DocStore(base_path=storage_path)
    repos = store.list_repos()
    latency_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "repos": repos,
        "count": len(repos),
        "_meta": {"latency_ms": latency_ms},
    }
