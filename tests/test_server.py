"""Tests for the MCP server module."""

import json
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from jdocmunch_mcp.server import list_tools, call_tool, main


class TestListTools:
    @pytest.mark.asyncio
    async def test_returns_10_tools(self):
        tools = await list_tools()
        assert len(tools) == 10

    @pytest.mark.asyncio
    async def test_tool_names(self):
        tools = await list_tools()
        names = {t.name for t in tools}
        expected = {
            "index_local", "index_repo", "list_repos",
            "get_toc", "get_toc_tree", "get_document_outline",
            "search_sections", "get_section", "get_sections", "delete_index",
        }
        assert names == expected

    @pytest.mark.asyncio
    async def test_each_tool_has_schema(self):
        tools = await list_tools()
        for tool in tools:
            assert tool.inputSchema is not None
            assert "type" in tool.inputSchema

    @pytest.mark.asyncio
    async def test_required_fields_defined(self):
        tools = await list_tools()
        # Tools that need 'repo' should have it in required
        for tool in tools:
            if tool.name not in ("index_local", "index_repo", "list_repos"):
                assert "required" in tool.inputSchema
                assert "repo" in tool.inputSchema["required"]


class TestCallTool:
    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        result = await call_tool("nonexistent_tool", {})
        assert len(result) == 1
        data = json.loads(result[0].text)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_list_repos_no_storage(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DOC_INDEX_PATH", str(tmp_path))
        result = await call_tool("list_repos", {})
        assert len(result) == 1
        data = json.loads(result[0].text)
        assert "repos" in data
        assert data["count"] == 0

    @pytest.mark.asyncio
    async def test_index_local_invalid_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DOC_INDEX_PATH", str(tmp_path))
        result = await call_tool("index_local", {"path": "/nonexistent/path"})
        data = json.loads(result[0].text)
        assert data["success"] is False


class TestCli:
    def test_version_flag_long(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["--version"])

        assert exc.value.code == 0
        out = capsys.readouterr().out.strip()
        assert out == "jdocmunch-mcp 0.1.0"

    def test_version_flag_short(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["-V"])

        assert exc.value.code == 0
        out = capsys.readouterr().out.strip()
        assert out == "jdocmunch-mcp 0.1.0"
