"""OpenAPI/Swagger parser: converts an OpenAPI 2.x/3.x spec to Markdown for section indexing.

Detects specs by content sniffing (looks for 'openapi:' or 'swagger:' keys).
Groups operations by tag, renders parameters/request body/responses, and appends
a Schemas section. The resulting Markdown is parsed by the Markdown parser so
heading structure drives section boundaries.
"""

import json
import re

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


_OPENAPI_SNIFF_RE = re.compile(
    r'(^|\n)\s*["\']?(?:openapi|swagger)["\']?\s*[=:]',
    re.MULTILINE,
)
_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "options", "head", "trace")


def sniff_openapi(content: str, ext: str) -> bool:
    """Return True if content looks like an OpenAPI/Swagger spec.

    Checks the file extension first (must be .yaml, .yml, or .json), then
    scans the first 2 KB for an 'openapi:' or 'swagger:' key.
    """
    if ext.lower() not in (".yaml", ".yml", ".json"):
        return False
    return bool(_OPENAPI_SNIFF_RE.search(content[:2048]))


def _load_spec(content: str) -> dict:
    """Parse YAML or JSON into a dict. Returns {} on failure."""
    if _YAML_AVAILABLE:
        try:
            spec = yaml.safe_load(content)
            if isinstance(spec, dict):
                return spec
        except Exception:
            pass
    # Fallback to JSON (handles .json files even without pyyaml)
    try:
        spec = json.loads(content)
        if isinstance(spec, dict):
            return spec
    except Exception:
        pass
    return {}


def _render_schema_type(schema: dict) -> str:
    """Return a short type string for a schema object."""
    if not isinstance(schema, dict):
        return ""
    ref = schema.get("$ref", "")
    if ref:
        return ref.split("/")[-1]
    t = schema.get("type", "")
    fmt = schema.get("format", "")
    if fmt:
        return f"{t}({fmt})" if t else fmt
    items = schema.get("items", {})
    if t == "array" and isinstance(items, dict):
        return f"array[{_render_schema_type(items)}]"
    return t


def _render_operation(method: str, path: str, op: dict) -> str:
    """Render one operation as a Markdown ### section."""
    lines = []
    summary = op.get("summary", "").strip()
    heading = f"### {method} {path}"
    if summary:
        heading += f" — {summary}"
    lines.append(heading)

    desc = op.get("description", "").strip()
    if desc and desc != summary:
        lines.append("")
        lines.append(desc)

    # Parameters
    params = [p for p in op.get("parameters", []) if isinstance(p, dict)]
    if params:
        lines.append("")
        lines.append("**Parameters:**")
        for p in params:
            name = p.get("name", "")
            location = p.get("in", "")
            required = "required" if p.get("required") else "optional"
            schema = p.get("schema", {})
            p_type = _render_schema_type(schema) if isinstance(schema, dict) else ""
            p_desc = p.get("description", "").strip()
            parts = [location, required]
            if p_type:
                parts.append(p_type)
            line = f"- `{name}` ({', '.join(parts)})"
            if p_desc:
                line += f" — {p_desc}"
            lines.append(line)

    # Request body (OpenAPI 3.x)
    req_body = op.get("requestBody", {})
    if isinstance(req_body, dict) and req_body:
        required_str = " (required)" if req_body.get("required") else ""
        rb_desc = req_body.get("description", "").strip()
        lines.append("")
        lines.append(f"**Request Body{required_str}:**")
        if rb_desc:
            lines.append(rb_desc)
        content_obj = req_body.get("content", {})
        for media_type, media_obj in content_obj.items():
            if not isinstance(media_obj, dict):
                continue
            schema = media_obj.get("schema", {})
            type_str = _render_schema_type(schema) if isinstance(schema, dict) else ""
            entry = f"- `{media_type}`"
            if type_str:
                entry += f" → `{type_str}`"
            lines.append(entry)

    # Responses
    responses = op.get("responses", {})
    if responses:
        lines.append("")
        lines.append("**Responses:**")
        for code, resp in responses.items():
            if isinstance(resp, dict):
                r_desc = resp.get("description", "").strip()
                lines.append(f"- `{code}` — {r_desc}")

    return "\n".join(lines)


def convert_openapi(content: str) -> str:
    """Convert an OpenAPI 2.x/3.x spec to a Markdown representation.

    Groups operations by tag, renders parameters/request body/responses, and
    appends a Schemas (or Definitions) section. Returns empty string on failure
    or if the content is not a valid OpenAPI spec.

    Args:
        content: Raw YAML or JSON string.

    Returns:
        Markdown string with # headings, suitable for parse_markdown().
        Returns empty string if parsing fails or spec has no openapi/swagger key.
    """
    spec = _load_spec(content)
    if not spec:
        return ""
    if "openapi" not in spec and "swagger" not in spec:
        return ""

    parts = []

    # ── Header ──────────────────────────────────────────────────────────────
    info = spec.get("info", {})
    title = info.get("title", "API Reference").strip()
    version = str(info.get("version", "")).strip()
    parts.append(f"# {title}")
    if version:
        parts.append(f"\nVersion: {version}")
    desc = info.get("description", "").strip()
    if desc:
        parts.append(f"\n{desc}")

    # ── Collect operations grouped by first tag ──────────────────────────────
    paths = spec.get("paths", {})
    tags_order: list = []
    tagged: dict = {}
    untagged: list = []

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method in _HTTP_METHODS:
            op = path_item.get(method)
            if not isinstance(op, dict):
                continue
            op_tags = op.get("tags", [])
            tag = op_tags[0] if op_tags else None
            entry = (method.upper(), path, op)
            if tag:
                if tag not in tagged:
                    tagged[tag] = []
                    tags_order.append(tag)
                tagged[tag].append(entry)
            else:
                untagged.append(entry)

    for tag in tags_order:
        parts.append(f"\n\n## {tag}")
        for method, path, op in tagged[tag]:
            parts.append(f"\n{_render_operation(method, path, op)}")

    if untagged:
        parts.append("\n\n## Operations")
        for method, path, op in untagged:
            parts.append(f"\n{_render_operation(method, path, op)}")

    # ── Schemas / Definitions ────────────────────────────────────────────────
    schemas = spec.get("components", {}).get("schemas", {})
    if not schemas:
        schemas = spec.get("definitions", {})  # OpenAPI 2.x

    if schemas:
        parts.append("\n\n## Schemas")
        for schema_name, schema in schemas.items():
            if not isinstance(schema, dict):
                continue
            parts.append(f"\n### {schema_name}")
            s_desc = schema.get("description", "").strip()
            if s_desc:
                parts.append(s_desc)
            props = schema.get("properties", {})
            required_props = schema.get("required", [])
            if props:
                parts.append("")
                parts.append("**Properties:**")
                for prop_name, prop_schema in props.items():
                    if not isinstance(prop_schema, dict):
                        continue
                    prop_type = _render_schema_type(prop_schema)
                    prop_desc = prop_schema.get("description", "").strip()
                    req_marker = " *(required)*" if prop_name in required_props else ""
                    line = f"- `{prop_name}`{req_marker}"
                    if prop_type:
                        line += f" (`{prop_type}`)"
                    if prop_desc:
                        line += f" — {prop_desc}"
                    parts.append(line)

    return "\n".join(parts)
