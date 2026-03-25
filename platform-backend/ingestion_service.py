from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from openai import AzureOpenAI


def _safe_json_loads(value: str) -> Optional[Dict[str, Any]]:
    try:
        cleaned = value.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except Exception:
        return None
    return None


def _infer_basic_type(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "string"
    if re.fullmatch(r"[-+]?\d+", text):
        return "integer"
    if re.fullmatch(r"[-+]?\d*\.\d+", text):
        return "float"
    if text.lower() in {"true", "false", "yes", "no"}:
        return "boolean"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return "date"
    return "string"


def _majority_type(samples: List[str]) -> str:
    counts: Dict[str, int] = {}
    for sample in samples:
        item_type = _infer_basic_type(sample)
        counts[item_type] = counts.get(item_type, 0) + 1
    if not counts:
        return "string"
    return sorted(counts.items(), key=lambda pair: pair[1], reverse=True)[0][0]


def _infer_domain_from_terms(terms: List[str]) -> str:
    joined = " ".join(terms).lower()
    if any(word in joined for word in ["revenue", "sales", "price", "amount", "invoice"]):
        return "sales"
    if any(word in joined for word in ["user", "email", "name", "age", "profile"]):
        return "users"
    if any(word in joined for word in ["product", "stock", "inventory", "qty", "warehouse"]):
        return "inventory"
    if any(word in joined for word in ["ticket", "issue", "incident", "support"]):
        return "support"
    return "general"


def _build_openai_client() -> Optional[AzureOpenAI]:
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_KEY") or os.getenv("AZURE_OPENAI_API_KEY")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION") or "2024-02-01"
    if not endpoint or not api_key:
        return None
    try:
        return AzureOpenAI(azure_endpoint=endpoint, api_key=api_key, api_version=api_version)
    except Exception:
        return None


def _chat_json(
    client: Optional[AzureOpenAI],
    prompt: str,
    *,
    model_name: Optional[str] = None,
    default: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if default is None:
        default = {}
    if client is None:
        return default

    deployment = model_name or os.getenv("AZURE_MODEL_DEPLOYMENT") or os.getenv("AZURE_OPENAI_DEPLOYMENT") or "gpt-4o"
    try:
        response = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": "Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1200,
            temperature=0.2,
        )
        content = response.choices[0].message.content or ""
        parsed = _safe_json_loads(content)
        return parsed or default
    except Exception:
        return default


def _resolve_canvas_asset_path(repo_root: Path, project_id: str, url: str) -> Optional[Path]:
    candidate = str(url or "").strip()
    if not candidate:
        return None

    marker = f"/api/canvas-assets/{project_id}/"
    if marker in candidate:
        suffix = candidate.split(marker, 1)[1]
        asset_path = (repo_root / "generated_code" / project_id / "canvas_assets" / suffix).resolve()
        base = (repo_root / "generated_code" / project_id / "canvas_assets").resolve()
        try:
            asset_path.relative_to(base)
            return asset_path if asset_path.exists() and asset_path.is_file() else None
        except Exception:
            return None
    return None


def _download_bytes(repo_root: Path, project_id: str, url: str) -> bytes:
    local_asset = _resolve_canvas_asset_path(repo_root, project_id, url)
    if local_asset is not None:
        return local_asset.read_bytes()

    with httpx.Client(timeout=20.0) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.content


def _analyze_csv(project_id: str, content_bytes: bytes, filename: str, client: Optional[AzureOpenAI]) -> Dict[str, Any]:
    text = content_bytes.decode("utf-8", errors="ignore")
    reader = csv.DictReader(StringIO(text))
    rows = []
    for idx, row in enumerate(reader):
        rows.append(row)
        if idx >= 49:
            break

    columns = reader.fieldnames or []
    types: Dict[str, str] = {}
    for column in columns:
        samples = [str(row.get(column, "")) for row in rows[:30]]
        types[column] = _majority_type(samples)

    domain = _infer_domain_from_terms(columns)

    suggestion_default = {
        "proposed_db_schema": f"table {Path(filename).stem}({', '.join(columns[:8])})",
        "suggested_endpoints": [f"GET /{domain}", f"POST /{domain}", f"GET /{domain}/summary"],
        "suggested_ui_components": ["table", "filters", "summary chart"],
    }
    suggestion_prompt = (
        f"CSV columns: {columns}\n"
        f"Detected types: {types}\n"
        f"Domain hint: {domain}\n"
        "Return JSON with keys: proposed_db_schema (string), suggested_endpoints (array, max 5), suggested_ui_components (array, max 5)."
    )
    suggestion = _chat_json(
        client,
        suggestion_prompt,
        model_name=os.getenv("AZURE_OPENAI_DEPLOYMENT_GPT4O_MINI") or os.getenv("AZURE_MODEL_DEPLOYMENT"),
        default=suggestion_default,
    )

    return {
        "project_id": project_id,
        "source_file": filename,
        "file_type": "csv",
        "domain": domain,
        "columns": columns,
        "types": types,
        "record_sample_count": len(rows),
        "proposed_db_schema": suggestion.get("proposed_db_schema", suggestion_default["proposed_db_schema"]),
        "suggested_endpoints": suggestion.get("suggested_endpoints", suggestion_default["suggested_endpoints"]),
        "suggested_ui_components": suggestion.get("suggested_ui_components", suggestion_default["suggested_ui_components"]),
    }


def _analyze_json_or_openapi(project_id: str, content_bytes: bytes, filename: str, client: Optional[AzureOpenAI]) -> Dict[str, Any]:
    text = content_bytes.decode("utf-8", errors="ignore")
    data = json.loads(text)
    is_openapi = isinstance(data, dict) and ("openapi" in data or "swagger" in data or "paths" in data)

    if is_openapi:
        paths = list((data.get("paths") or {}).keys())
        schemas = list((((data.get("components") or {}).get("schemas") or {}).keys()))
        default = {
            "domain": "api",
            "proposed_db_schema": "Entities inferred from OpenAPI schemas",
            "suggested_endpoints": paths[:5],
            "suggested_ui_components": ["api docs", "endpoint tester", "admin table"],
        }
        prompt = (
            f"OpenAPI paths: {paths[:15]}\n"
            f"OpenAPI schemas: {schemas[:15]}\n"
            "Return JSON with keys: domain, proposed_db_schema, suggested_endpoints(array), suggested_ui_components(array)."
        )
        suggestion = _chat_json(client, prompt, default=default)
        return {
            "project_id": project_id,
            "source_file": filename,
            "file_type": "openapi",
            "domain": suggestion.get("domain", default["domain"]),
            "paths": paths[:20],
            "schemas": schemas[:20],
            "proposed_db_schema": suggestion.get("proposed_db_schema", default["proposed_db_schema"]),
            "suggested_endpoints": suggestion.get("suggested_endpoints", default["suggested_endpoints"]),
            "suggested_ui_components": suggestion.get("suggested_ui_components", default["suggested_ui_components"]),
        }

    preview = text[:1600]
    keys = list(data.keys())[:25] if isinstance(data, dict) else []
    domain = _infer_domain_from_terms(keys)
    default = {
        "domain": domain,
        "proposed_db_schema": "JSON data model inferred from top-level keys",
        "suggested_endpoints": [f"GET /{domain}", f"POST /{domain}", f"GET /{domain}/:id"],
        "suggested_ui_components": ["table", "details panel", "form"],
    }
    prompt = (
        f"JSON top-level keys: {keys}\n"
        f"Preview: {preview}\n"
        "Return JSON with keys: domain, proposed_db_schema, suggested_endpoints(array), suggested_ui_components(array)."
    )
    suggestion = _chat_json(client, prompt, default=default)

    return {
        "project_id": project_id,
        "source_file": filename,
        "file_type": "json",
        "domain": suggestion.get("domain", default["domain"]),
        "top_level_keys": keys,
        "proposed_db_schema": suggestion.get("proposed_db_schema", default["proposed_db_schema"]),
        "suggested_endpoints": suggestion.get("suggested_endpoints", default["suggested_endpoints"]),
        "suggested_ui_components": suggestion.get("suggested_ui_components", default["suggested_ui_components"]),
    }


def _analyze_image(project_id: str, content_bytes: bytes, filename: str, client: Optional[AzureOpenAI]) -> Dict[str, Any]:
    default = {
        "page_name": Path(filename).stem or "Wireframe",
        "components": [],
        "layout": "Unable to extract layout details",
        "navigation_flow": [],
        "frontend_task_list": [],
    }
    if client is None:
        return {
            "project_id": project_id,
            "source_file": filename,
            "file_type": "image",
            **default,
        }

    import base64

    image_base64 = base64.b64encode(content_bytes).decode("utf-8")
    deployment = os.getenv("AZURE_MODEL_DEPLOYMENT") or os.getenv("AZURE_OPENAI_DEPLOYMENT") or "gpt-4o"
    try:
        response = client.chat.completions.create(
            model=deployment,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Analyze this UI image/wireframe and return JSON with keys: "
                                "page_name, components(array), layout, navigation_flow(array), frontend_task_list(array)."
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                    ],
                }
            ],
            max_tokens=1200,
        )
        parsed = _safe_json_loads(response.choices[0].message.content or "") or default
    except Exception:
        parsed = default

    return {
        "project_id": project_id,
        "source_file": filename,
        "file_type": "image",
        "page_name": parsed.get("page_name", default["page_name"]),
        "components": parsed.get("components", default["components"]),
        "layout": parsed.get("layout", default["layout"]),
        "navigation_flow": parsed.get("navigation_flow", default["navigation_flow"]),
        "frontend_task_list": parsed.get("frontend_task_list", default["frontend_task_list"]),
    }


def _analyze_document(project_id: str, content_bytes: bytes, filename: str, client: Optional[AzureOpenAI]) -> Dict[str, Any]:
    extracted = content_bytes.decode("utf-8", errors="ignore")[:5000]
    default = {
        "extracted_text": extracted[:1500],
        "user_stories": [],
        "technical_constraints": [],
        "key_value_pairs": {},
    }
    prompt = (
        f"Document content preview:\n{extracted[:2500]}\n\n"
        "Return JSON with keys: extracted_text, user_stories(array), technical_constraints(array), key_value_pairs(object)."
    )
    parsed = _chat_json(client, prompt, default=default)
    return {
        "project_id": project_id,
        "source_file": filename,
        "file_type": "document",
        "extracted_text": parsed.get("extracted_text", default["extracted_text"]),
        "user_stories": parsed.get("user_stories", default["user_stories"]),
        "technical_constraints": parsed.get("technical_constraints", default["technical_constraints"]),
        "key_value_pairs": parsed.get("key_value_pairs", default["key_value_pairs"]),
    }


def _analyze_canvas(project_id: str, canvas_data: Any) -> Dict[str, Any]:
    data = canvas_data if isinstance(canvas_data, dict) else {}
    nodes = data.get("nodes") if isinstance(data.get("nodes"), list) else []
    edges = data.get("edges") if isinstance(data.get("edges"), list) else []
    drawings = data.get("drawings") if isinstance(data.get("drawings"), list) else []

    node_titles: List[str] = []
    node_types: Dict[str, int] = {}
    for node in nodes[:200]:
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("type") or "unknown")
        node_types[node_type] = node_types.get(node_type, 0) + 1
        payload = node.get("data") if isinstance(node.get("data"), dict) else {}
        title = str(payload.get("title") or payload.get("label") or "").strip()
        if title:
            node_titles.append(title)

    return {
        "project_id": project_id,
        "file_type": "canvas",
        "node_count": len(nodes),
        "edge_count": len(edges),
        "drawing_count": len(drawings),
        "node_type_counts": node_types,
        "node_titles": node_titles[:25],
    }


def _detect_file_type(filename: str, url: str) -> str:
    source = f"{filename} {url}".lower()
    if source.endswith(".csv"):
        return "csv"
    if source.endswith(".json"):
        return "json"
    if ".yaml" in source or ".yml" in source:
        return "openapi"
    if any(ext in source for ext in [".png", ".jpg", ".jpeg", ".webp"]):
        return "image"
    if any(ext in source for ext in [".pdf", ".docx", ".txt", ".md"]):
        return "document"
    return "document"


def _build_questioning_context_markdown(context: Dict[str, Any]) -> str:
    lines: List[str] = ["INGESTION CONTEXT (AUTO-GENERATED):"]

    file_results = context.get("file_results") or []
    canvas_result = context.get("canvas_result")
    unified_summary = context.get("combined_summary")
    task_seeds = context.get("task_ledger_seeds") or []

    for idx, result in enumerate(file_results, start=1):
        file_name = result.get("source_file") or f"file_{idx}"
        file_type = result.get("file_type") or "unknown"
        lines.append(f"- File {idx}: {file_name} ({file_type})")
        if result.get("domain"):
            lines.append(f"  - Domain: {result['domain']}")
        if result.get("proposed_db_schema"):
            lines.append(f"  - Proposed schema: {result['proposed_db_schema']}")
        if result.get("suggested_endpoints"):
            lines.append(f"  - Endpoints: {', '.join(result['suggested_endpoints'][:5])}")
        if result.get("suggested_ui_components"):
            lines.append(f"  - UI components: {', '.join(result['suggested_ui_components'][:5])}")
        if result.get("user_stories"):
            stories = result.get("user_stories") or []
            if stories:
                lines.append(f"  - User stories: {stories[0]}")

    if isinstance(canvas_result, dict):
        lines.append("- Canvas analysis:")
        lines.append(f"  - Nodes: {canvas_result.get('node_count', 0)} | Edges: {canvas_result.get('edge_count', 0)} | Drawings: {canvas_result.get('drawing_count', 0)}")
        titles = canvas_result.get("node_titles") or []
        if titles:
            lines.append(f"  - Key canvas items: {', '.join(titles[:8])}")

    if unified_summary:
        lines.append(f"- Combined summary: {unified_summary}")

    if task_seeds:
        lines.append("- Suggested starter tasks:")
        for task in task_seeds[:8]:
            lines.append(f"  - {task}")

    return "\n".join(lines)


def _synthesize_context(client: Optional[AzureOpenAI], file_results: List[Dict[str, Any]], canvas_result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    context_parts: List[str] = []
    for item in file_results[:8]:
        context_parts.append(json.dumps(item, ensure_ascii=False)[:1200])
    if canvas_result:
        context_parts.append(json.dumps(canvas_result, ensure_ascii=False)[:1200])

    default = {
        "combined_summary": "Uploaded files and canvas context analyzed. Use inferred domain, schema, and UI signals to guide questioning.",
        "task_ledger_seeds": [],
    }
    prompt = (
        "Given the following ingestion outputs, return JSON with keys: combined_summary and task_ledger_seeds (array).\n\n"
        + "\n\n".join(context_parts)
    )
    return _chat_json(client, prompt, default=default)


def build_ingestion_context(
    *,
    repo_root: Path,
    project_id: str,
    reference_files: List[Dict[str, str]],
    include_canvas: bool,
    canvas_data: Any,
) -> Dict[str, Any]:
    client = _build_openai_client()
    file_results: List[Dict[str, Any]] = []

    for item in reference_files:
        filename = str(item.get("filename") or "uploaded_file").strip()
        url = str(item.get("url") or "").strip()
        if not url:
            continue

        try:
            payload = _download_bytes(repo_root, project_id, url)
            file_type = _detect_file_type(filename, url)
            if file_type == "csv":
                analyzed = _analyze_csv(project_id, payload, filename, client)
            elif file_type in {"json", "openapi"}:
                analyzed = _analyze_json_or_openapi(project_id, payload, filename, client)
            elif file_type == "image":
                analyzed = _analyze_image(project_id, payload, filename, client)
            else:
                analyzed = _analyze_document(project_id, payload, filename, client)

            analyzed["source_url"] = url
            file_results.append(analyzed)
        except Exception as exc:
            file_results.append(
                {
                    "project_id": project_id,
                    "source_file": filename,
                    "source_url": url,
                    "file_type": _detect_file_type(filename, url),
                    "error": f"Failed to analyze file: {exc}",
                }
            )

    canvas_result = _analyze_canvas(project_id, canvas_data) if include_canvas else None

    synthesis = _synthesize_context(client, file_results, canvas_result)
    combined_summary = synthesis.get("combined_summary")
    task_ledger_seeds = synthesis.get("task_ledger_seeds") or []

    context = {
        "project_id": project_id,
        "generated_at": datetime.utcnow().isoformat(),
        "file_results": file_results,
        "canvas_result": canvas_result,
        "combined_summary": combined_summary,
        "task_ledger_seeds": task_ledger_seeds,
    }
    context["questioning_context_markdown"] = _build_questioning_context_markdown(context)

    out_dir = (repo_root / "generated_code" / project_id / "ingestion").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    latest_file = out_dir / "ingestion_context_latest.json"
    versioned_file = out_dir / f"ingestion_context_{ts}.json"
    content = json.dumps(context, indent=2, ensure_ascii=False)
    latest_file.write_text(content, encoding="utf-8")
    versioned_file.write_text(content, encoding="utf-8")

    context["persisted_files"] = {
        "latest": str(latest_file),
        "versioned": str(versioned_file),
    }
    return context
