"""Nested TOC tree per document."""

import time
from typing import Optional

from ..storage import DocStore
from ..storage.token_tracker import estimate_savings, record_savings, cost_avoided


def get_toc_tree(repo: str, storage_path: Optional[str] = None) -> dict:
    """Return a nested table of contents tree, grouped by document.

    Each document contains a tree of sections structured by parent/child
    relationships. Content is excluded.
    """
    t0 = time.perf_counter()
    store = DocStore(base_path=storage_path)
    owner, name = store._resolve_repo(repo)
    index = store.load_index(owner, name)

    if not index:
        return {"error": f"Repo not found: {repo}"}

    # Group sections by doc_path, sorted by byte_start
    docs: dict = {}
    for sec in sorted(index.sections, key=lambda s: (s.get("doc_path", ""), s.get("byte_start", 0))):
        dp = sec.get("doc_path", "")
        docs.setdefault(dp, []).append(sec)

    def _make_node(sec: dict) -> dict:
        return {
            "id": sec.get("id"),
            "title": sec.get("title"),
            "level": sec.get("level"),
            "summary": sec.get("summary"),
            "byte_start": sec.get("byte_start"),
            "byte_end": sec.get("byte_end"),
            "children": [],
        }

    tree_docs = []
    for doc_path, sections in docs.items():
        # Build id -> node map
        nodes: dict = {s["id"]: _make_node(s) for s in sections if "id" in s}
        roots = []
        for sec in sections:
            sec_id = sec.get("id")
            if not sec_id or sec_id not in nodes:
                continue
            parent_id = sec.get("parent_id", "")
            if parent_id and parent_id in nodes:
                nodes[parent_id]["children"].append(nodes[sec_id])
            else:
                roots.append(nodes[sec_id])

        tree_docs.append({
            "doc_path": doc_path,
            "sections": roots,
        })

    raw_bytes = sum(len(s.get("content", "").encode("utf-8")) for s in index.sections)
    response_str = str(tree_docs)
    response_bytes = len(response_str.encode("utf-8"))
    tokens_saved = estimate_savings(raw_bytes, response_bytes)
    total = record_savings(tokens_saved, storage_path)
    ca = cost_avoided(tokens_saved, total)

    latency_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "repo": f"{owner}/{name}",
        "documents": tree_docs,
        "doc_count": len(tree_docs),
        "_meta": {
            "latency_ms": latency_ms,
            "sections_returned": len(index.sections),
            "tokens_saved": tokens_saved,
            **ca,
        },
    }
