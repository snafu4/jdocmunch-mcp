"""MCP server for jdocmunch-mcp."""

import argparse
import asyncio
import json
import os
import sys
import traceback
from typing import Any, Optional

from mcp.server import Server
from mcp.types import Tool, TextContent

from . import __version__
from .tools.index_local import index_local
from .tools.index_repo import index_repo
from .tools.list_repos import list_repos
from .tools.get_toc import get_toc
from .tools.get_toc_tree import get_toc_tree
from .tools.get_document_outline import get_document_outline
from .tools.search_sections import search_sections
from .tools.get_section import get_section
from .tools.get_sections import get_sections
from .tools.delete_index import delete_index


server = Server("jdocmunch-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available tools."""
    return [
        Tool(
            name="index_local",
            description="Index a local folder containing documentation files (.md, .txt, .rst). Parses by heading hierarchy into sections for efficient retrieval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to local folder (absolute or relative, supports ~ for home directory)"
                    },
                    "use_ai_summaries": {
                        "type": "boolean",
                        "description": "Use AI to generate section summaries (requires ANTHROPIC_API_KEY or GOOGLE_API_KEY). When false, uses heading text.",
                        "default": True
                    },
                    "extra_ignore_patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Additional gitignore-style patterns to exclude from indexing"
                    },
                    "follow_symlinks": {
                        "type": "boolean",
                        "description": "Whether to follow symlinks. Default false for security.",
                        "default": False
                    }
                },
                "required": ["path"]
            }
        ),
        Tool(
            name="index_repo",
            description="Index a GitHub repository's documentation. Fetches .md/.txt files, parses sections, and saves to local storage.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "GitHub repository URL or owner/repo string"
                    },
                    "use_ai_summaries": {
                        "type": "boolean",
                        "description": "Use AI to generate section summaries.",
                        "default": True
                    }
                },
                "required": ["url"]
            }
        ),
        Tool(
            name="list_repos",
            description="List all indexed documentation repositories.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="get_toc",
            description="Get a flat table of contents for all sections in a repo, sorted by document order. Content is excluded — use get_section to retrieve content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {
                        "type": "string",
                        "description": "Repository identifier (owner/repo or just repo name)"
                    }
                },
                "required": ["repo"]
            }
        ),
        Tool(
            name="get_toc_tree",
            description="Get a nested table of contents tree per document. Shows parent/child heading relationships. Content is excluded.",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {
                        "type": "string",
                        "description": "Repository identifier (owner/repo or just repo name)"
                    }
                },
                "required": ["repo"]
            }
        ),
        Tool(
            name="get_document_outline",
            description="Get the section hierarchy for a single document file, without content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {
                        "type": "string",
                        "description": "Repository identifier"
                    },
                    "doc_path": {
                        "type": "string",
                        "description": "Path to the document within the repository (e.g., 'README.md')"
                    }
                },
                "required": ["repo", "doc_path"]
            }
        ),
        Tool(
            name="search_sections",
            description="Search sections by weighted scoring across title, summary, tags, and content. Returns summaries only — use get_section for full content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {
                        "type": "string",
                        "description": "Repository identifier"
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query"
                    },
                    "doc_path": {
                        "type": "string",
                        "description": "Optional: limit search to a specific document"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return",
                        "default": 10
                    }
                },
                "required": ["repo", "query"]
            }
        ),
        Tool(
            name="get_section",
            description="Retrieve the full content of a specific section using byte-range reads. Use after identifying section IDs via search_sections or get_toc.",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {
                        "type": "string",
                        "description": "Repository identifier"
                    },
                    "section_id": {
                        "type": "string",
                        "description": "Section ID from get_toc, search_sections, or get_document_outline"
                    },
                    "verify": {
                        "type": "boolean",
                        "description": "Verify content hash matches stored hash (detects source drift)",
                        "default": False
                    }
                },
                "required": ["repo", "section_id"]
            }
        ),
        Tool(
            name="get_sections",
            description="Batch content retrieval for multiple sections in one call.",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {
                        "type": "string",
                        "description": "Repository identifier"
                    },
                    "section_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of section IDs to retrieve"
                    },
                    "verify": {
                        "type": "boolean",
                        "description": "Verify content hashes",
                        "default": False
                    }
                },
                "required": ["repo", "section_ids"]
            }
        ),
        Tool(
            name="delete_index",
            description="Remove a repo index and its cached raw files.",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {
                        "type": "string",
                        "description": "Repository identifier (owner/repo or just repo name)"
                    }
                },
                "required": ["repo"]
            }
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    storage_path = os.environ.get("DOC_INDEX_PATH")

    try:
        if name == "index_local":
            result = index_local(
                path=arguments["path"],
                use_ai_summaries=arguments.get("use_ai_summaries", True),
                storage_path=storage_path,
                extra_ignore_patterns=arguments.get("extra_ignore_patterns"),
                follow_symlinks=arguments.get("follow_symlinks", False),
            )
        elif name == "index_repo":
            result = await index_repo(
                url=arguments["url"],
                use_ai_summaries=arguments.get("use_ai_summaries", True),
                storage_path=storage_path,
            )
        elif name == "list_repos":
            result = list_repos(storage_path=storage_path)
        elif name == "get_toc":
            result = get_toc(
                repo=arguments["repo"],
                storage_path=storage_path,
            )
        elif name == "get_toc_tree":
            result = get_toc_tree(
                repo=arguments["repo"],
                storage_path=storage_path,
            )
        elif name == "get_document_outline":
            result = get_document_outline(
                repo=arguments["repo"],
                doc_path=arguments["doc_path"],
                storage_path=storage_path,
            )
        elif name == "search_sections":
            result = search_sections(
                repo=arguments["repo"],
                query=arguments["query"],
                doc_path=arguments.get("doc_path"),
                max_results=arguments.get("max_results", 10),
                storage_path=storage_path,
            )
        elif name == "get_section":
            result = get_section(
                repo=arguments["repo"],
                section_id=arguments["section_id"],
                verify=arguments.get("verify", False),
                storage_path=storage_path,
            )
        elif name == "get_sections":
            result = get_sections(
                repo=arguments["repo"],
                section_ids=arguments["section_ids"],
                verify=arguments.get("verify", False),
                storage_path=storage_path,
            )
        elif name == "delete_index":
            result = delete_index(
                repo=arguments["repo"],
                storage_path=storage_path,
            )
        else:
            result = {"error": f"Unknown tool: {name}"}

        if isinstance(result, dict):
            result.setdefault("_meta", {})["powered_by"] = "jdocmunch-mcp by jgravelle · https://github.com/jgravelle/jdocmunch-mcp"
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    except Exception as e:
        print(traceback.format_exc(), file=sys.stderr)
        return [TextContent(type="text", text=json.dumps({"error": str(e)}, indent=2))]


async def run_server():
    """Run the MCP server."""
    from jdocmunch_mcp import __version__
    from mcp.server.stdio import stdio_server
    print(f"jdocmunch-mcp {__version__} by jgravelle · https://github.com/jgravelle/jdocmunch-mcp", file=sys.stderr)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


def main(argv: Optional[list] = None):
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="jdocmunch-mcp",
        description="Run the jDocMunch MCP stdio server.",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.parse_args(argv)
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
