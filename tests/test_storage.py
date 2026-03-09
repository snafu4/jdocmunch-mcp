"""Tests for storage module."""

import threading
import pytest
import tempfile
from pathlib import Path

from jdocmunch_mcp.parser import parse_file
from jdocmunch_mcp.storage.doc_store import DocStore, DocIndex
from jdocmunch_mcp.storage.token_tracker import estimate_savings, cost_avoided, record_savings


SAMPLE_MD = """# Root

Intro content.

## Section A

Content for A.

### Subsection A1

Deep content.

## Section B

Content for B.
"""


def make_store(tmp_path):
    return DocStore(base_path=str(tmp_path))


def make_sections_and_files():
    sections = parse_file(SAMPLE_MD, "README.md", "test/repo")
    raw_files = {"README.md": SAMPLE_MD}
    doc_types = {".md": 1}
    return sections, raw_files, doc_types


class TestDocStore:
    def test_save_and_load(self, tmp_path):
        store = make_store(tmp_path)
        sections, raw_files, doc_types = make_sections_and_files()

        index = store.save_index("test", "repo", sections, raw_files, doc_types)
        assert index is not None
        assert index.repo == "test/repo"

        loaded = store.load_index("test", "repo")
        assert loaded is not None
        assert loaded.repo == "test/repo"
        assert len(loaded.sections) == len(sections)

    def test_section_content_retrieval(self, tmp_path):
        store = make_store(tmp_path)
        sections, raw_files, doc_types = make_sections_and_files()
        store.save_index("test", "repo", sections, raw_files, doc_types)

        index = store.load_index("test", "repo")
        assert index is not None

        # Pick a non-empty section
        target = next((s for s in index.sections if s.get("title") == "Section A"), None)
        assert target is not None

        content = store.get_section_content("test", "repo", target["id"])
        assert content is not None
        assert "Content for A" in content

    def test_list_repos(self, tmp_path):
        store = make_store(tmp_path)
        sections, raw_files, doc_types = make_sections_and_files()
        store.save_index("test", "repo", sections, raw_files, doc_types)
        repos = store.list_repos()
        assert len(repos) == 1
        assert repos[0]["repo"] == "test/repo"

    def test_delete_index(self, tmp_path):
        store = make_store(tmp_path)
        sections, raw_files, doc_types = make_sections_and_files()
        store.save_index("test", "repo", sections, raw_files, doc_types)
        deleted = store.delete_index("test", "repo")
        assert deleted is True
        assert store.load_index("test", "repo") is None

    def test_atomic_write(self, tmp_path):
        """Save should leave no .tmp files on success."""
        store = make_store(tmp_path)
        sections, raw_files, doc_types = make_sections_and_files()
        store.save_index("test", "repo", sections, raw_files, doc_types)
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_path_traversal_protection(self, tmp_path):
        """Unsafe doc paths should raise ValueError."""
        store = make_store(tmp_path)
        sections, raw_files, doc_types = make_sections_and_files()
        raw_files["../../etc/passwd"] = "evil"
        with pytest.raises(ValueError):
            store.save_index("test", "repo", sections, raw_files, doc_types)

    def test_resolve_repo_slash(self, tmp_path):
        store = make_store(tmp_path)
        owner, name = store._resolve_repo("foo/bar")
        assert owner == "foo"
        assert name == "bar"

    def test_resolve_repo_bare(self, tmp_path):
        store = make_store(tmp_path)
        sections, raw_files, doc_types = make_sections_and_files()
        store.save_index("local", "myrepo", sections, raw_files, doc_types)
        owner, name = store._resolve_repo("myrepo")
        assert owner == "local"
        assert name == "myrepo"

    def test_resolve_repo_glob_injection(self, tmp_path):
        """Glob metacharacters in repo name should not match unintended repos."""
        store = make_store(tmp_path)
        sections, raw_files, doc_types = make_sections_and_files()
        store.save_index("local", "realrepo", sections, raw_files, doc_types)
        # Passing "*" should not match realrepo via glob expansion
        owner, name = store._resolve_repo("*")
        # Falls back to ("local", "*") — not ("local", "realrepo")
        assert name != "realrepo"

    def test_directory_layout(self, tmp_path):
        """Index and content should be stored under base_path/owner/name."""
        store = make_store(tmp_path)
        sections, raw_files, doc_types = make_sections_and_files()
        store.save_index("myowner", "myname", sections, raw_files, doc_types)
        assert (tmp_path / "myowner" / "myname.json").exists()
        assert (tmp_path / "myowner" / "myname").is_dir()

    def test_repo_slug_no_collision(self, tmp_path):
        """Different owner/name combos that share a flat slug must not collide."""
        store = make_store(tmp_path)
        sections, raw_files, doc_types = make_sections_and_files()
        store.save_index("foo-bar", "baz", sections, raw_files, doc_types)
        store.save_index("foo", "bar-baz", sections, raw_files, doc_types)
        repos = store.list_repos()
        repo_ids = {r["repo"] for r in repos}
        assert "foo-bar/baz" in repo_ids
        assert "foo/bar-baz" in repo_ids


class TestDocIndexSearch:
    def setup_method(self):
        self.sections, _, _ = make_sections_and_files()
        self.index = DocIndex(
            repo="test/repo",
            owner="test",
            name="repo",
            indexed_at="2026-01-01",
            doc_paths=["README.md"],
            doc_types={".md": 1},
            sections=[s.to_dict() for s in self.sections],
        )

    def test_search_by_title(self):
        results = self.index.search("Section A")
        assert len(results) > 0
        assert any(r["title"] == "Section A" for r in results)

    def test_search_case_insensitive(self):
        results = self.index.search("section a")
        assert len(results) > 0

    def test_search_no_content_in_results(self):
        results = self.index.search("content")
        for r in results:
            assert "content" not in r

    def test_search_max_results(self):
        results = self.index.search("content", max_results=2)
        assert len(results) <= 2

    def test_search_empty_query(self):
        results = self.index.search("xyzzy_nonexistent_42")
        assert results == []


class TestTokenTracker:
    def test_estimate_savings(self):
        assert estimate_savings(1000, 200) == (1000 - 200) // 4
        assert estimate_savings(100, 200) == 0  # no negative savings

    def test_cost_avoided(self):
        ca = cost_avoided(1000, 5000)
        assert "cost_avoided" in ca
        assert "total_cost_avoided" in ca
        assert "claude_opus" in ca["cost_avoided"]

    def test_record_savings_thread_safety(self, tmp_path):
        """Concurrent record_savings calls must not lose increments."""
        n_threads = 20
        increment = 100
        errors = []

        def do_record():
            try:
                record_savings(increment, base_path=str(tmp_path))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=do_record) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        from jdocmunch_mcp.storage.token_tracker import get_total_saved
        total = get_total_saved(base_path=str(tmp_path))
        assert total == n_threads * increment


SAMPLE_MD2 = """# Root

Updated intro.

## Section A

Updated content for A.

## Section C

Brand new section.
"""


class TestIncrementalIndexing:
    def test_detect_no_changes(self, tmp_path):
        store = make_store(tmp_path)
        sections, raw_files, doc_types = make_sections_and_files()
        store.save_index("test", "repo", sections, raw_files, doc_types)

        changed, new, deleted = store.detect_changes("test", "repo", raw_files)
        assert changed == []
        assert new == []
        assert deleted == []

    def test_detect_changed_file(self, tmp_path):
        store = make_store(tmp_path)
        sections, raw_files, doc_types = make_sections_and_files()
        store.save_index("test", "repo", sections, raw_files, doc_types)

        current = {"README.md": SAMPLE_MD2}
        changed, new, deleted = store.detect_changes("test", "repo", current)
        assert "README.md" in changed
        assert new == []
        assert deleted == []

    def test_detect_new_and_deleted(self, tmp_path):
        store = make_store(tmp_path)
        sections, raw_files, doc_types = make_sections_and_files()
        store.save_index("test", "repo", sections, raw_files, doc_types)

        current = {"GUIDE.md": SAMPLE_MD2}  # README.md removed, GUIDE.md added
        changed, new, deleted = store.detect_changes("test", "repo", current)
        assert "GUIDE.md" in new
        assert "README.md" in deleted
        assert changed == []

    def test_no_changes_returns_early(self, tmp_path):
        store = make_store(tmp_path)
        sections, raw_files, doc_types = make_sections_and_files()
        saved = store.save_index("test", "repo", sections, raw_files, doc_types)
        original_count = len(saved.sections)

        # No-op incremental save
        updated = store.incremental_save(
            owner="test", name="repo",
            changed_files=[], new_files=[], deleted_files=[],
            new_sections=[], raw_files={}, doc_types={},
        )
        assert updated is not None
        assert len(updated.sections) == original_count

    def test_incremental_save_changed_file(self, tmp_path):
        store = make_store(tmp_path)
        sections, raw_files, doc_types = make_sections_and_files()
        store.save_index("test", "repo", sections, raw_files, doc_types)

        new_sections = parse_file(SAMPLE_MD2, "README.md", "test/repo")
        updated = store.incremental_save(
            owner="test", name="repo",
            changed_files=["README.md"], new_files=[], deleted_files=[],
            new_sections=new_sections,
            raw_files={"README.md": SAMPLE_MD2},
            doc_types={".md": 1},
        )
        assert updated is not None
        # Old README.md sections replaced by new ones
        titles = [s["title"] for s in updated.sections]
        assert "Section C" in titles   # new section from SAMPLE_MD2
        assert "Section B" not in titles  # only in SAMPLE_MD, not SAMPLE_MD2

    def test_incremental_save_deleted_file(self, tmp_path):
        store = make_store(tmp_path)
        # Index two files
        s1 = parse_file(SAMPLE_MD, "README.md", "test/repo")
        s2 = parse_file(SAMPLE_MD2, "GUIDE.md", "test/repo")
        raw = {"README.md": SAMPLE_MD, "GUIDE.md": SAMPLE_MD2}
        store.save_index("test", "repo", s1 + s2, raw, {".md": 2})

        # Delete GUIDE.md
        updated = store.incremental_save(
            owner="test", name="repo",
            changed_files=[], new_files=[], deleted_files=["GUIDE.md"],
            new_sections=[], raw_files={}, doc_types={},
        )
        assert updated is not None
        doc_paths = {s["doc_path"] for s in updated.sections}
        assert "GUIDE.md" not in doc_paths
        assert "README.md" in doc_paths
        assert "GUIDE.md" not in updated.doc_paths

    def test_incremental_content_retrievable(self, tmp_path):
        store = make_store(tmp_path)
        sections, raw_files, doc_types = make_sections_and_files()
        store.save_index("test", "repo", sections, raw_files, doc_types)

        new_sections = parse_file(SAMPLE_MD2, "README.md", "test/repo")
        store.incremental_save(
            owner="test", name="repo",
            changed_files=["README.md"], new_files=[], deleted_files=[],
            new_sections=new_sections,
            raw_files={"README.md": SAMPLE_MD2},
            doc_types={".md": 1},
        )

        # Section content must be retrievable after incremental update
        index = store.load_index("test", "repo")
        sec_c = next((s for s in index.sections if s["title"] == "Section C"), None)
        assert sec_c is not None
        content = store.get_section_content("test", "repo", sec_c["id"], _index=index)
        assert content is not None
        assert "Brand new section" in content
