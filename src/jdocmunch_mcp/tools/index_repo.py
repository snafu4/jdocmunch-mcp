"""Index GitHub repository tool — fetch, parse, summarize, save."""

import asyncio
import os
import time
from typing import Optional
from urllib.parse import urlparse

import httpx

from ..parser import parse_file, preprocess_content, ALL_EXTENSIONS
from ..security import is_secret_file
from ..storage import DocStore
from ..summarizer import summarize_sections
from ._constants import SKIP_PATTERNS


def parse_github_url(url: str) -> tuple:
    """Extract (owner, repo) from GitHub URL or owner/repo string."""
    url = url.removesuffix(".git")
    if "/" in url and "://" not in url:
        parts = url.split("/")
        return parts[0], parts[1]
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    parts = path.split("/")
    if len(parts) >= 2:
        return parts[0], parts[1]
    raise ValueError(f"Could not parse GitHub URL: {url}")


def _should_skip(path: str) -> bool:
    normalized = "/" + path.replace("\\", "/")
    for pat in SKIP_PATTERNS:
        if ("/" + pat) in normalized:
            return True
    return False


async def fetch_repo_tree(
    owner: str, repo: str, token: Optional[str] = None, client: Optional[httpx.AsyncClient] = None
) -> list:
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD"
    params = {"recursive": "1"}
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    if client:
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json().get("tree", [])
    async with httpx.AsyncClient() as c:
        response = await c.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json().get("tree", [])


async def fetch_file_content(
    owner: str, repo: str, path: str, token: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    headers = {"Accept": "application/vnd.github.v3.raw"}
    if token:
        headers["Authorization"] = f"token {token}"
    if client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.text
    async with httpx.AsyncClient() as c:
        response = await c.get(url, headers=headers)
        response.raise_for_status()
        return response.text


async def fetch_gitignore(
    owner: str, repo: str, token: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[str]:
    try:
        return await fetch_file_content(owner, repo, ".gitignore", token, client=client)
    except Exception:
        return None


def discover_doc_files(tree_entries: list, max_files: int = 500, gitignore_spec=None) -> list:
    """Filter tree entries to doc files."""
    import os as _os

    files = []
    for entry in tree_entries:
        if entry.get("type") != "blob":
            continue
        path = entry.get("path", "")
        size = entry.get("size", 0)

        _, ext = _os.path.splitext(path)
        if ext.lower() not in ALL_EXTENSIONS:
            continue

        if _should_skip(path):
            continue

        if is_secret_file(path):
            continue

        if size > 500 * 1024:
            continue

        if gitignore_spec and gitignore_spec.match_file(path):
            continue

        files.append(path)

    return files[:max_files]


async def index_repo(
    url: str,
    use_ai_summaries: bool = True,
    github_token: Optional[str] = None,
    storage_path: Optional[str] = None,
    incremental: bool = True,
) -> dict:
    """Index a GitHub repository's documentation.

    Args:
        url: GitHub repository URL or owner/repo string.
        use_ai_summaries: Whether to use AI for section summaries.
        github_token: GitHub API token (optional).
        storage_path: Custom storage path.
        incremental: When True and an existing index exists, only re-index changed files.

    Returns:
        Dict with indexing results.
    """
    t0 = time.perf_counter()

    try:
        owner, repo = parse_github_url(url)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    if not github_token:
        github_token = os.environ.get("GITHUB_TOKEN")

    warnings = []

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                tree_entries = await fetch_repo_tree(owner, repo, github_token, client=client)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    return {"success": False, "error": f"Repository not found: {owner}/{repo}"}
                elif e.response.status_code == 403:
                    return {"success": False, "error": "GitHub API rate limit exceeded. Set GITHUB_TOKEN."}
                raise

            gitignore_spec = None
            gitignore_content = await fetch_gitignore(owner, repo, github_token, client=client)
            if gitignore_content:
                import pathspec
                try:
                    gitignore_spec = pathspec.PathSpec.from_lines("gitignore", gitignore_content.splitlines())
                except Exception:
                    pass

            source_files = discover_doc_files(tree_entries, gitignore_spec=gitignore_spec)
            if not source_files:
                return {"success": False, "error": "No documentation files found"}

            semaphore = asyncio.Semaphore(10)

            async def fetch_with_limit(path: str) -> tuple:
                async with semaphore:
                    try:
                        content = await fetch_file_content(owner, repo, path, github_token, client=client)
                        return path, content
                    except Exception:
                        return path, ""

            tasks = [fetch_with_limit(p) for p in source_files]
            file_contents = await asyncio.gather(*tasks)

        import os as _os
        repo_id = f"{owner}/{repo}"
        store = DocStore(base_path=storage_path)

        # Build current_files map (preprocessed content keyed by path)
        current_files: dict = {}
        for path, content in file_contents:
            if not content:
                continue
            _, ext = _os.path.splitext(path)
            if ext.lower() not in ALL_EXTENSIONS:
                continue
            try:
                current_files[path] = preprocess_content(content, path)
            except Exception:
                warnings.append(f"Failed to preprocess {path}")

        # --- Incremental path ---
        if incremental and store.load_index(owner, repo) is not None:
            changed, new, deleted = store.detect_changes(owner, repo, current_files)

            if not changed and not new and not deleted:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                return {
                    "success": True,
                    "message": "No changes detected",
                    "repo": f"{owner}/{repo}",
                    "incremental": True,
                    "changed": 0, "new": 0, "deleted": 0,
                    "_meta": {"latency_ms": latency_ms},
                }

            files_to_parse = set(changed) | set(new)
            new_sections = []
            raw_subset: dict = {}
            doc_types: dict = {}

            for path in files_to_parse:
                content = current_files[path]
                raw_subset[path] = content
                _, ext = _os.path.splitext(path)
                try:
                    sections = parse_file(content, path, repo_id)
                    if sections:
                        new_sections.extend(sections)
                        doc_types[ext.lower()] = doc_types.get(ext.lower(), 0) + 1
                except Exception:
                    warnings.append(f"Failed to parse {path}")

            new_sections = summarize_sections(new_sections, use_ai=use_ai_summaries)

            updated = store.incremental_save(
                owner=owner, name=repo,
                changed_files=changed, new_files=new, deleted_files=deleted,
                new_sections=new_sections, raw_files=raw_subset, doc_types=doc_types,
            )

            latency_ms = int((time.perf_counter() - t0) * 1000)
            result = {
                "success": True,
                "repo": f"{owner}/{repo}",
                "incremental": True,
                "changed": len(changed), "new": len(new), "deleted": len(deleted),
                "section_count": len(updated.sections) if updated else 0,
                "indexed_at": updated.indexed_at if updated else "",
                "_meta": {"latency_ms": latency_ms},
            }
            if warnings:
                result["warnings"] = warnings
            return result

        # --- Full index path ---
        all_sections = []
        doc_types = {}
        raw_files: dict = {}
        parsed_files = []

        for path, content in current_files.items():
            _, ext = _os.path.splitext(path)
            try:
                sections = parse_file(content, path, repo_id)
                if sections:
                    all_sections.extend(sections)
                    doc_types[ext.lower()] = doc_types.get(ext.lower(), 0) + 1
                    raw_files[path] = content
                    parsed_files.append(path)
            except Exception:
                warnings.append(f"Failed to parse {path}")

        if not all_sections:
            return {"success": False, "error": "No sections extracted"}

        all_sections = summarize_sections(all_sections, use_ai=use_ai_summaries)

        saved = store.save_index(
            owner=owner,
            name=repo,
            sections=all_sections,
            raw_files=raw_files,
            doc_types=doc_types,
        )

        latency_ms = int((time.perf_counter() - t0) * 1000)
        result = {
            "success": True,
            "repo": f"{owner}/{repo}",
            "indexed_at": saved.indexed_at,
            "file_count": len(parsed_files),
            "section_count": len(all_sections),
            "doc_types": doc_types,
            "files": parsed_files[:20],
            "_meta": {"latency_ms": latency_ms},
        }

        if warnings:
            result["warnings"] = warnings

        return result

    except Exception as e:
        return {"success": False, "error": f"Indexing failed: {str(e)}"}
