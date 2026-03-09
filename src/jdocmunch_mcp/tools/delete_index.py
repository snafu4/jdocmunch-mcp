"""Delete a repo index."""

import time
from typing import Optional

from ..storage import DocStore


def delete_index(repo: str, storage_path: Optional[str] = None) -> dict:
    """Remove a repo index and its raw content cache."""
    t0 = time.perf_counter()
    store = DocStore(base_path=storage_path)
    owner, name = store._resolve_repo(repo)
    deleted = store.delete_index(owner, name)
    latency_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "success": deleted,
        "repo": f"{owner}/{name}",
        "message": "Index deleted." if deleted else "Index not found.",
        "_meta": {"latency_ms": latency_ms},
    }
