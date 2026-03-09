# jdocmunch-mcp — Project Brief

See also: `C:\MCPs\CLAUDE.md` for universal workflow and shell conventions.

## Current State
- **Version:** 1.1.0 (PyPI + GitHub)
- **INDEX_VERSION:** 1
- **Tests:** 201 passed
- **Python:** >=3.10

## Purpose
Companion to jcodemunch-mcp. Owns **documentation section indexing** — section-level
search across human-readable doc files. Does NOT parse code symbols (that's jcodemunch).

## Key Files
```
src/jdocmunch_mcp/
  server.py                    # MCP tool definitions + call_tool dispatcher
  storage/
    doc_store.py               # DocIndex dataclass, DocStore CRUD, detect_changes, incremental_save
                               # O(1) section lookup via __post_init__ id dict
  parser/
    sections.py                # Section dataclass + shared parsing utilities
    markdown_parser.py         # ATX + setext headings, MDX preprocessing
    rst_parser.py              # RST heading/adornment parser
    asciidoc_parser.py         # AsciiDoc = heading parser
    notebook_parser.py         # Jupyter .ipynb JSON → markdown sections
    html_parser.py             # HTML → text, chrome stripped
    text_parser.py             # Plain text paragraph splitting
    openapi_parser.py          # OpenAPI 3.x / Swagger 2.x (content-sniffed from .yaml/.json)
    hierarchy.py               # Parent/child heading relationships
  tools/
    index_local.py             # Local folder doc indexer
    index_repo.py              # GitHub repo doc indexer
    get_toc.py                 # Table of contents (flat)
    get_toc_tree.py            # Table of contents (nested)
    get_document_outline.py    # File-level outline
    get_section.py             # Single section by id
    get_sections.py            # Multiple sections by id list
    search_sections.py         # Full-text search across sections
    list_repos.py
    delete_index.py
    _constants.py
```

## Supported Formats
| Extension(s) | Parser |
|-------------|--------|
| `.md`, `.markdown`, `.mdx` | markdown_parser (ATX + setext + MDX preprocessing) |
| `.txt` | text_parser (paragraph splitting) |
| `.rst` | rst_parser (heading adornment detection) |
| `.adoc`, `.asciidoc`, `.asc` | asciidoc_parser (`=` heading levels) |
| `.ipynb` | notebook_parser (JSON → markdown cells) |
| `.html`, `.htm` | html_parser (BeautifulSoup, chrome stripped) |
| `.yaml`, `.yml`, `.json` | openapi_parser (OpenAPI 3.x / Swagger 2.x, content-sniffed; plain YAML/JSON skipped) |

## Architecture Notes
- `DocStore.detect_changes()` + `DocStore.incremental_save()` — incremental indexing
- O(1) section lookup via `DocIndex.__post_init__` id dict
- `pyyaml>=6.0` is a **hard dependency** (in pyproject.toml)
- INDEX_VERSION=1; older-version rejection logic same pattern as jcodemunch

## PR / Issue History

### Merged / Closed
| # | What |
|---|------|
| #1 | MCP version conflict with jcodemunch-mcp — fixed |

### Open PRs / Issues
None currently open.

## Version History
| Version | What |
|---------|------|
| 0.1.1–0.1.4 | Pre-stable iterations (incremental indexing, O(1) lookup, perf fixes) |
| 1.0.0 | Stable release — all 7 formats complete, 201 tests |
| 1.0.1 | powered_by attribution added to tool responses |
| 1.1.0 | OpenAPI 3.x / Swagger 2.x parser; .yaml/.yml/.json content-sniffed; 201 tests |

## Ecosystem Boundary
- jdocmunch owns: section search, TOC, document outlines, doc file indexing
- jcodemunch owns: symbol extraction, file outlines, code search
- Do NOT add docstring/module-doc parsing to jcodemunch — that's here
