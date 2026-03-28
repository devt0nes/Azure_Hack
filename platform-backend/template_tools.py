"""
template_tools.py  —  Template Library Tools for AI Agents
===========================================================

Adds two tools to the agent tool surface:

    search_template(query, category?, framework?, tags?, max_results?)
        Query the TemplateLibrary for reusable frontend snippets.
        Returns lightweight metadata — no code — so the agent can pick
        the right template before committing.

    use_template(template_id, target_path, line_number)
        Fetch a template by id and paste its code AS-IS into the exact file path
        at the requested line number. If the file does not exist, create it with
        template code.

--------------------------------------------------------------------
HOW TO WIRE IN  (three options, pick one)
--------------------------------------------------------------------

Option 1 — plug into an existing ToolRegistry (no changes to tooly.py):

    from tooly import ToolRegistry
    from template_tools import attach_template_tools

    registry = ToolRegistry()
    attach_template_tools(registry)          # done

Option 2 — plug into a CWDAwareToolRegistry from agents_combined.py:

    # Wherever a CWDAwareToolRegistry is constructed:
    from template_tools import attach_template_tools

    cwd_registry = CWDAwareToolRegistry(tool_registry, allowed_root)
    attach_template_tools(cwd_registry)      # done

Option 3 — standalone (template tools only):

    from template_tools import TemplateToolRegistry
    registry = TemplateToolRegistry()

--------------------------------------------------------------------
COSMOS DB DOCUMENT SCHEMA  (TemplateLibrary container)
--------------------------------------------------------------------

{
  "id":             "navbar-responsive-v1",
  "name":           "Responsive Navbar",
  "description":    "Mobile-first navbar with hamburger toggle...",
  "category":       "navigation",           # navigation | layout | forms | auth | data | misc
  "framework":      "react",                # react | next | vue | html | vanilla
  "tags":           ["navbar", "responsive", "tailwind"],
  "file_extension": ".jsx",
  "code":           "<full component source>",   # copied verbatim into workspace
  "usage_count":    0                       # auto-incremented by use_template
}

--------------------------------------------------------------------
ENV VARS  (same pattern as the rest of the project)
--------------------------------------------------------------------

  COSMOS_CONNECTION_STR   full connection string  (preferred)
  OR
  COSMOS_ENDPOINT         account URL
  COSMOS_KEY              account key

  COSMOS_DB_NAME              database name   (default: agentic-nexus-db)
  COSMOS_TEMPLATE_CONTAINTER  container name  (default: TemplateLibrary)
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Optional SDK import — degrade gracefully when azure-cosmos is not installed
# ---------------------------------------------------------------------------
try:
    from azure.cosmos import CosmosClient  # type: ignore
    _COSMOS_AVAILABLE = True
except ImportError:
    CosmosClient = None
    _COSMOS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Internal: build a Cosmos container client from env vars
# ---------------------------------------------------------------------------

def _build_cosmos_container():
    """Return a Cosmos container client or None if not configured / SDK missing."""
    if not _COSMOS_AVAILABLE:
        return None

    conn_str = os.getenv("COSMOS_CONNECTION_STR", "").strip()
    url      = os.getenv("COSMOS_ENDPOINT",       "").strip()
    key      = os.getenv("COSMOS_KEY",            "").strip()
    db_name  = (os.getenv("COSMOS_DB_NAME", "agentic-nexus-db") or "agentic-nexus-db").strip()
    ctr_name = (os.getenv("COSMOS_TEMPLATE_CONTAINTER", "TemplateLibrary") or "TemplateLibrary").strip()

    try:
        if conn_str:
            client = CosmosClient.from_connection_string(conn_str)
        elif url and key:
            client = CosmosClient(url, credential=key)
        else:
            return None

        return client.get_database_client(db_name).get_container_client(ctr_name)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# TemplateTools — core logic, no dependency on ToolRegistry shape
# ---------------------------------------------------------------------------

class TemplateTools:
    """
    Core implementation of search_template and use_template.

    Accepts an optional FilesTools instance (from tooly.py) so that
    use_template can write directly into the agent's sandboxed workspace.
    """

    def __init__(self, files_tool=None):
        self.files_tool = files_tool
        self._container = None      # lazily initialised on first call

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_container(self):
        if self._container is None:
            self._container = _build_cosmos_container()
        return self._container

    def _cosmos_ok(self) -> bool:
        return self._get_container() is not None

    def _not_configured_error(self) -> str:
        if not _COSMOS_AVAILABLE:
            return (
                "ERROR: azure-cosmos SDK is not installed. "
                "Run: pip install azure-cosmos"
            )
        return (
            "ERROR: Cosmos DB template library is not configured. "
            "Set COSMOS_CONNECTION_STR (or COSMOS_ENDPOINT + COSMOS_KEY) env vars."
        )

    def _find_safe_insert_line(self, lines: List[str], anchor_line: int) -> int:
        """
        Return a 1-based line number where new code should be inserted safely.

        Strategy:
          - Treat anchor_line as a location hint, not an insertion point.
          - If anchor is inside a brace-delimited block, insert after the block ends.
          - Otherwise, insert after the current non-empty statement region.
          - Never return a line that overwrites existing content.
        """
        total = len(lines)
        if total == 0:
            return 1

        anchor_line = max(1, min(anchor_line, total))
        anchor_idx = anchor_line - 1

        # Move anchor to nearest non-empty line around the provided line.
        if not lines[anchor_idx].strip():
            down = anchor_idx
            up = anchor_idx
            found = None
            while down < total or up >= 0:
                if down < total and lines[down].strip():
                    found = down
                    break
                if up >= 0 and lines[up].strip():
                    found = up
                    break
                down += 1
                up -= 1
            if found is not None:
                anchor_idx = found

        # Find innermost brace block containing anchor_idx.
        stack: List[int] = []
        containing_start = None
        containing_end = None

        for idx, line in enumerate(lines):
            for ch in line:
                if ch == "{":
                    stack.append(idx)
                elif ch == "}" and stack:
                    start = stack.pop()
                    end = idx
                    if start <= anchor_idx <= end:
                        containing_start = start
                        containing_end = end

        if containing_start is not None and containing_end is not None:
            # Insert after the closing brace line.
            return containing_end + 2

        # Fallback: insert after contiguous non-empty lines from anchor.
        end_idx = anchor_idx
        while end_idx + 1 < total and lines[end_idx + 1].strip():
            end_idx += 1
        return end_idx + 2

    # ------------------------------------------------------------------
    # search_template
    # ------------------------------------------------------------------

    def search_template(
        self,
        query: str,
        category: Optional[str] = None,
        framework: Optional[str] = None,
        tags: Optional[List[str]] = None,
        max_results: int = 5,
    ) -> str:
        """
        Search the TemplateLibrary for reusable frontend code snippets.

        Returns a JSON object with a 'results' list. Each result contains
        template metadata but NOT the code — call use_template with the
        returned template_id to copy the code into your workspace.
        """
        if not self._cosmos_ok():
            return self._not_configured_error()

        container = self._get_container()

        try:
            conditions: List[str] = []
            params: List[Dict[str, Any]] = []

            # Word-level search across name + description
            words = [w.strip() for w in query.split() if w.strip()][:6]
            if words:
                word_clauses = []
                for i, word in enumerate(words):
                    pn = f"@wn{i}"
                    pd = f"@wd{i}"
                    word_clauses.append(
                        f"(CONTAINS(LOWER(c.name), {pn}) OR CONTAINS(LOWER(c.description), {pd}))"
                    )
                    params += [
                        {"name": pn, "value": word.lower()},
                        {"name": pd, "value": word.lower()},
                    ]
                conditions.append(f"({' OR '.join(word_clauses)})")

            # Strict category filter
            if category:
                conditions.append("LOWER(c.category) = @category")
                params.append({"name": "@category", "value": category.lower()})

            # Strict framework filter
            if framework:
                conditions.append("LOWER(c.framework) = @framework")
                params.append({"name": "@framework", "value": framework.lower()})

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            limit = min(max(1, int(max_results)), 20)

            # Select only metadata — never pull the code field during search
            sql = (
                "SELECT c.id, c.name, c.description, c.category, "
                "c.framework, c.tags, c.file_extension, c.usage_count "
                f"FROM c {where} OFFSET 0 LIMIT {limit}"
            )

            items = list(
                container.query_items(
                    query=sql,
                    parameters=params if params else None,
                    enable_cross_partition_query=True,
                )
            )

            # Post-filter: all requested tags must be present
            if tags:
                required = {t.lower() for t in tags}
                items = [
                    item for item in items
                    if required.issubset({t.lower() for t in (item.get("tags") or [])})
                ]

            if not items:
                hint_parts = [f"query='{query}'"]
                if category:
                    hint_parts.append(f"category='{category}'")
                if framework:
                    hint_parts.append(f"framework='{framework}'")
                if tags:
                    hint_parts.append(f"tags={tags}")
                return json.dumps({
                    "results": [],
                    "count":   0,
                    "message": (
                        f"No templates found for {', '.join(hint_parts)}. "
                        "Try broader search terms or omit optional filters."
                    ),
                })

            results = [
                {
                    "template_id":    item.get("id"),
                    "name":           item.get("name"),
                    "description":    item.get("description"),
                    "category":       item.get("category"),
                    "framework":      item.get("framework"),
                    "tags":           item.get("tags", []),
                    "file_extension": item.get("file_extension", ".jsx"),
                    "usage_count":    item.get("usage_count", 0),
                }
                for item in items
            ]

            return json.dumps({"results": results, "count": len(results)}, indent=2)

        except Exception as e:
            return json.dumps({"error": f"Template search failed: {str(e)}"})

    # ------------------------------------------------------------------
    # use_template
    # ------------------------------------------------------------------

    def use_template(self, template_id: str, target_path: str, line_number: int) -> str:
        """
        Paste a template's code AS-IS into a target file at a specific line.

        Steps:
          1. Fetch the full Cosmos document for template_id.
          2. Extract the 'code' field.
          3. If target_path exists, insert template code at line_number.
             If it does not exist, create it with template code.
             *** DO NOT modify or rewrite the code. Use it exactly as stored. ***
          4. Increment usage_count on the Cosmos document (best-effort).
        """
        if not self._cosmos_ok():
            return self._not_configured_error()

        if not template_id or not target_path:
            return "ERROR: template_id and target_path are required."

        try:
            line_number = int(line_number)
        except Exception:
            return "ERROR: line_number must be an integer."

        if line_number < 1:
            return "ERROR: line_number must be >= 1."

        container = self._get_container()
        item = None

        # Fast path: direct read by id
        try:
            item = container.read_item(item=template_id, partition_key=template_id)
        except Exception:
            pass

        # Fallback: cross-partition query by id field
        if item is None:
            try:
                results = list(
                    container.query_items(
                        query="SELECT * FROM c WHERE c.id = @id",
                        parameters=[{"name": "@id", "value": template_id}],
                        enable_cross_partition_query=True,
                    )
                )
                if results:
                    item = results[0]
            except Exception as e:
                return json.dumps({"error": f"Failed to fetch template '{template_id}': {str(e)}"})

        if item is None:
            return json.dumps({"error": f"Template '{template_id}' not found in the library."})

        # Validate code field exists
        print("🔥 NEW TEMPLATE TOOL LOADED 🔥")
        code = item.get("code") or item.get("content", {}).get("code")
        if not code:
            return json.dumps({
        "error": (
            f"Template '{template_id}' exists but no usable code found. "
            "Expected either 'code' or 'content.code' in the document."
        )
    })

        # Write code verbatim into the workspace
        if self.files_tool is not None:
            read_result = self.files_tool.read_file(target_path)
            inserted_at_line = line_number

            if isinstance(read_result, str) and read_result.startswith("ERROR"):
                write_result = self.files_tool.write_file(target_path, code)
                if isinstance(write_result, str) and write_result.startswith("ERROR"):
                    return json.dumps({
                        "error": f"Failed to create template file: {write_result}"
                    })
                action = "created"
                inserted_at_line = 1
            else:
                existing_content = read_result if isinstance(read_result, str) else ""
                lines = existing_content.splitlines(keepends=True)

                if line_number > len(lines) + 1:
                    return json.dumps({
                        "error": (
                            f"line_number {line_number} is out of range for file with "
                            f"{len(lines)} lines. Use 1 to {len(lines) + 1}."
                        )
                    })

                safe_line = self._find_safe_insert_line(lines, line_number)
                insert_idx = min(max(safe_line - 1, 0), len(lines))
                template_block = code if code.endswith("\n") else (code + "\n")
                lines.insert(insert_idx, template_block)
                updated_content = "".join(lines)
                inserted_at_line = insert_idx + 1

                write_result = self.files_tool.write_file(target_path, updated_content)
                if isinstance(write_result, str) and write_result.startswith("ERROR"):
                    return json.dumps({
                        "error": f"Failed to update target file: {write_result}"
                    })
                action = "inserted"
        else:
            return json.dumps({
                "warning": (
                    "No FilesTools instance wired into TemplateTools. "
                    "Returning code directly — write it to disk yourself."
                ),
                "template_id":      template_id,
                "target_path":      target_path,
                "line_number":      line_number,
                "code":             code,
            })

        # Bump usage_count — best-effort, never fail the overall call
        try:
            item["usage_count"] = int(item.get("usage_count", 0)) + 1
            container.replace_item(item=template_id, body=item)
        except Exception:
            pass

        return json.dumps({
            "success":          True,
            "template_id":      template_id,
            "name":             item.get("name", template_id),
            "target_path":      target_path,
            "line_number":      line_number,
            "inserted_at_line": inserted_at_line,
            "action":           action,
            "category":         item.get("category"),
            "framework":        item.get("framework"),
            "message": (
                f"✅ Template '{item.get('name', template_id)}' {action} in "
                f"'{target_path}' (anchor line {line_number}, inserted at line {inserted_at_line}). "
                "Do NOT rewrite the code — "
                "use it exactly as placed."
            ),
        })


# ---------------------------------------------------------------------------
# OpenAI-compatible tool definitions  (same shape as tooly.py)
# ---------------------------------------------------------------------------

TEMPLATE_TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_template",
            "description": (
                "Search the shared template library for reusable frontend code snippets "
                "(components, layouts, forms, navbars, auth pages, data tables, etc.).\n"
                "ALWAYS call this BEFORE building any UI component from scratch. "
                "If a matching template exists, call use_template to copy it into your "
                "workspace instead of writing new code."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Natural-language description of the component you need. "
                            "Examples: 'responsive navbar with hamburger menu', "
                            "'login form with email and password', "
                            "'product card with image and price'."
                        ),
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional category filter.",
                        "enum": ["navigation", "layout", "forms", "auth", "data", "misc"],
                    },
                    "framework": {
                        "type": "string",
                        "description": "Optional framework filter.",
                        "enum": ["react", "next", "vue", "html", "vanilla"],
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional list of tags that must ALL be present on a result. "
                            "Examples: ['tailwind', 'responsive'], ['typescript', 'accessible']."
                        ),
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (1–20). Default: 5.",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "use_template",
            "description": (
                "Copy a template's code AS-IS from the library into your workspace. "
                "Use the template_id returned by search_template.\n"
                "IMPORTANT: Do NOT modify or rewrite the code after calling this — "
                "place it at target_path exactly as stored. "
                "Paste into target_path at the exact line_number. "
                "You may import or call it from other files you write."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "template_id": {
                        "type": "string",
                        "description": (
                            "The template_id value from a search_template result. "
                            "Example: 'navbar-responsive-v1'."
                        ),
                    },
                    "target_path": {
                        "type": "string",
                        "description": (
                            "Exact workspace file path where template code should be pasted. "
                            "If the file does not exist, it will be created with the template code. "
                            "Examples: '/workspace/frontend/components/Navbar.jsx', "
                            "'/workspace/frontend/pages/Login.tsx'."
                        ),
                    },
                    "line_number": {
                        "type": "integer",
                        "description": (
                            "1-based line number where template code should be inserted in target_path. "
                            "Use 1 to insert at file start, or existing_line_count + 1 to append."
                        ),
                    },
                },
                "required": ["template_id", "target_path", "line_number"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# attach_template_tools()
# Patches an existing ToolRegistry or CWDAwareToolRegistry in-place.
# ---------------------------------------------------------------------------

def attach_template_tools(registry) -> None:
    """
    Inject search_template and use_template into an existing registry.

    Works with:
      - tooly.ToolRegistry
      - agents_combined.CWDAwareToolRegistry

    After this call:
      - registry.get_tool_definitions() includes both new tools
      - registry.execute_tool() dispatches them correctly
    """

    # Resolve FilesTools
    files_tool = None
    inner = getattr(registry, "tool_registry", None)   # CWDAwareToolRegistry path
    if inner is not None:
        files_tool = getattr(inner, "files", None)
    if files_tool is None:
        files_tool = getattr(registry, "files", None)  # plain ToolRegistry path

    _t = TemplateTools(files_tool=files_tool)

    # ---- patch get_tool_definitions ----
    _orig_defs = registry.get_tool_definitions

    def _patched_get_tool_definitions():
        return _orig_defs() + TEMPLATE_TOOL_DEFINITIONS

    registry.get_tool_definitions = _patched_get_tool_definitions

    # ---- patch execute_tool ----
    _orig_exec = registry.execute_tool

    def _patched_execute_tool(function_name, function_args):
        if function_name == "search_template":
            return _t.search_template(
                query=function_args.get("query", ""),
                category=function_args.get("category"),
                framework=function_args.get("framework"),
                tags=function_args.get("tags"),
                max_results=int(function_args.get("max_results", 5) or 5),
            )
        if function_name == "use_template":
            return _t.use_template(
                template_id=function_args.get("template_id", ""),
                target_path=function_args.get("target_path", ""),
                line_number=function_args.get("line_number", 1),
            )
        return _orig_exec(function_name, function_args)

    registry.execute_tool = _patched_execute_tool


# ---------------------------------------------------------------------------
# TemplateToolRegistry — standalone registry (template tools only)
# ---------------------------------------------------------------------------

class TemplateToolRegistry:
    """
    Standalone registry exposing only search_template and use_template.
    Follows the exact same interface as tooly.ToolRegistry.

    Usage:
        from template_tools import TemplateToolRegistry
        registry = TemplateToolRegistry()
    """

    def __init__(self, files_tool=None):
        self.templates = TemplateTools(files_tool=files_tool)

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        return list(TEMPLATE_TOOL_DEFINITIONS)

    def execute_tool(self, function_name: str, function_args: Dict[str, Any]) -> str:
        if function_name == "search_template":
            return self.templates.search_template(
                query=function_args.get("query", ""),
                category=function_args.get("category"),
                framework=function_args.get("framework"),
                tags=function_args.get("tags"),
                max_results=int(function_args.get("max_results", 5) or 5),
            )
        if function_name == "use_template":
            return self.templates.use_template(
                template_id=function_args.get("template_id", ""),
                target_path=function_args.get("target_path", ""),
                line_number=function_args.get("line_number", 1),
            )
        return (
            f"ERROR: Unknown tool '{function_name}'. "
            "TemplateToolRegistry only handles search_template and use_template."
        )