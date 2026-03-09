"""Flat TOC: all sections sorted by doc_path + byte_start."""

import time
from typing import Optional

from ..storage import DocStore
from ..storage.token_tracker import estimate_savings, record_savings, cost_avoided, get_total_saved


def get_toc(repo: str, storage_path: Optional[str] = None) -> dict:
    """Return a flat table of contents for all sections in a repo.

    Sections are sorted by (doc_path, byte_start). Content is excluded.
    """
    t0 = time.perf_counter()
    store = DocStore(base_path=storage_path)
    owner, name = store._resolve_repo(repo)
    index = store.load_index(owner, name)

    if not index:
        return {"error": f"Repo not found: {repo}"}

    sections = sorted(
        index.sections,
        key=lambda s: (s.get("doc_path", ""), s.get("byte_start", 0))
    )

    toc = []
    for sec in sections:
        toc.append({
            "id": sec.get("id"),
            "doc_path": sec.get("doc_path"),
            "title": sec.get("title"),
            "level": sec.get("level"),
            "summary": sec.get("summary"),
            "parent_id": sec.get("parent_id"),
            "children": sec.get("children"),
            "byte_start": sec.get("byte_start"),
            "byte_end": sec.get("byte_end"),
        })

    # Estimate token savings vs returning full content
    raw_bytes = sum(len(s.get("content", "").encode("utf-8")) for s in index.sections)
    response_bytes = sum(len(str(t).encode("utf-8")) for t in toc)
    tokens_saved = estimate_savings(raw_bytes, response_bytes)
    total = record_savings(tokens_saved, storage_path)
    ca = cost_avoided(tokens_saved, total)

    latency_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "repo": f"{owner}/{name}",
        "sections": toc,
        "section_count": len(toc),
        "_meta": {
            "latency_ms": latency_ms,
            "sections_returned": len(toc),
            "tokens_saved": tokens_saved,
            **ca,
        },
    }
