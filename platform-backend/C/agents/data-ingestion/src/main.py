import os
import json
import pandas as pd
from io import BytesIO
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../../../"))
from shared.clients import call_gpt4o, call_gpt4o_mini, call_gpt4o_vision, download_blob_bytes
from shared.models import SchemaResult, VisionResult, DocumentResult, UnifiedContext
from shared.cosmos_client import write_schema_result, write_unified_context

load_dotenv()

app = FastAPI(title="Data Ingestion Agent")

# ─────────────────────────────────────────────
# REQUEST MODELS
# ─────────────────────────────────────────────

class IngestRequest(BaseModel):
    project_id: str
    blob_url: str
    file_type: str  # "csv", "json", "openapi", "png", "pdf", "docx"

class MultiIngestRequest(BaseModel):
    project_id: str
    files: list[IngestRequest]

# ─────────────────────────────────────────────
# CSV PARSER
# ─────────────────────────────────────────────

def ingest_csv(project_id: str, blob_url: str) -> SchemaResult:
    raw = download_blob_bytes(blob_url)
    df = pd.read_csv(BytesIO(raw))

    columns = df.columns.tolist()
    types = {col: str(df[col].dtype) for col in columns}

    col_str = " ".join(columns).lower()
    if any(word in col_str for word in ["revenue", "sales", "price", "amount"]):
        domain = "sales"
    elif any(word in col_str for word in ["user", "email", "name", "age"]):
        domain = "users"
    elif any(word in col_str for word in ["product", "stock", "inventory", "qty"]):
        domain = "inventory"
    else:
        domain = "general"

    prompt = f"""
    I have a CSV with these columns: {columns}
    Column types: {types}
    Inferred domain: {domain}

    Return a JSON object with:
    - proposed_db_schema: a short SQL CREATE TABLE statement
    - suggested_endpoints: list of 3 REST API endpoint strings e.g. ["GET /sales", "POST /sales", "GET /sales/summary"]
    - suggested_ui_components: list of 3 UI components (e.g. table, chart)

    Return JSON only, no explanation.
    """
    raw_response = call_gpt4o_mini(prompt)

    try:
        clean = raw_response.strip().replace("```json", "").replace("```", "")
        suggestions = json.loads(clean)
    except Exception:
        suggestions = {
            "proposed_db_schema": "Could not generate",
            "suggested_endpoints": [],
            "suggested_ui_components": []
        }

    return SchemaResult(
        project_id=project_id,
        file_type="csv",
        columns=columns,
        types=types,
        domain=domain,
        proposed_db_schema=suggestions.get("proposed_db_schema"),
        suggested_endpoints=suggestions.get("suggested_endpoints", []),
        suggested_ui_components=suggestions.get("suggested_ui_components", [])
    )

# ─────────────────────────────────────────────
# JSON / OPENAPI PARSER
# ─────────────────────────────────────────────

def ingest_json(project_id: str, blob_url: str) -> SchemaResult:
    raw = download_blob_bytes(blob_url)
    data = json.loads(raw)

    prompt = f"""
    I have a JSON file with this structure (first 500 chars): {str(data)[:500]}

    Return a JSON object with:
    - proposed_db_schema: a short description of the data model
    - suggested_endpoints: list of 3 REST API endpoint strings e.g. ["GET /items", "POST /items", "DELETE /items"]
    - suggested_ui_components: list of 3 UI components
    - domain: one word describing the domain (e.g. users, orders, producsts)

    Return JSON only, no explanation.
    """
    print("Sending prompt to GPT-4o:", prompt[:200])
    raw_response = call_gpt4o_mini(prompt)
    print("GPT-4o response:", raw_response)
    try:
        clean = raw_response.strip().replace("```json", "").replace("```", "")
        suggestions = json.loads(clean)
    except Exception:
        suggestions = {"proposed_db_schema": "Could not generate", "suggested_endpoints": [], "suggested_ui_components": [], "domain": "general"}

    return SchemaResult(
        project_id=project_id,
        file_type="json",
        domain=suggestions.get("domain", "general"),
        proposed_db_schema=suggestions.get("proposed_db_schema"),
        suggested_endpoints=suggestions.get("suggested_endpoints", []),
        suggested_ui_components=suggestions.get("suggested_ui_components", [])
    )

def ingest_openapi(project_id: str, blob_url: str) -> SchemaResult:
    raw = download_blob_bytes(blob_url)
    data = json.loads(raw)

    paths = list(data.get("paths", {}).keys())
    schemas = list(data.get("components", {}).get("schemas", {}).keys())

    prompt = f"""
    I have an OpenAPI spec with these paths: {paths[:10]}
    And these schemas: {schemas[:10]}

    Return a JSON object with:
    - proposed_db_schema: summary of the main entities
    - suggested_endpoints: the 3 most important endpoint strings e.g. ["GET /users", "POST /users", "DELETE /users/id"]
    - suggested_ui_components: list of 3 UI components to build
    - domain: one word describing the domain

    Return JSON only, no explanation.
    """
    raw_response = call_gpt4o_mini(prompt)

    try:
        clean = raw_response.strip().replace("```json", "").replace("```", "")
        suggestions = json.loads(clean)
    except Exception:
        suggestions = {"proposed_db_schema": "Could not generate", "suggested_endpoints": paths[:3], "suggested_ui_components": [], "domain": "api"}

    return SchemaResult(
        project_id=project_id,
        file_type="openapi",
        domain=suggestions.get("domain", "api"),
        proposed_db_schema=suggestions.get("proposed_db_schema"),
        suggested_endpoints=suggestions.get("suggested_endpoints", []),
        suggested_ui_components=suggestions.get("suggested_ui_components", [])
    )

# ─────────────────────────────────────────────
# PNG VISION PARSER
# ─────────────────────────────────────────────

def ingest_image(project_id: str, blob_url: str) -> VisionResult:
    image_bytes = download_blob_bytes(blob_url)
    print("Image bytes length:", len(image_bytes))
    print("First 20 bytes:", image_bytes[:20])

    wireframe_prompt = """
    This is a UI wireframe. Extract the following and return as JSON:
    - page_name: name of the page
    - components: list of UI component name strings (e.g. ["button", "input", "table"])
    - layout: brief description of the layout
    - navigation_flow: list of navigation action strings
    - frontend_task_list: list of frontend development task strings to build this page

    Return JSON only, no explanation.
    """

    raw_response = call_gpt4o_vision(image_bytes, wireframe_prompt)
    print("GPT-4o Vision raw response:", raw_response)

    try:
        clean = raw_response.strip().replace("```json", "").replace("```", "")
        result = json.loads(clean)
    except Exception as e:
        print("JSON parse error:", e)
        result = {
            "page_name": "Unknown",
            "components": [],
            "layout": "Could not parse",
            "navigation_flow": [],
            "frontend_task_list": []
        }

    return VisionResult(
        project_id=project_id,
        page_name=result.get("page_name", "Unknown"),
        components=result.get("components", []),
        layout=result.get("layout", ""),
        navigation_flow=result.get("navigation_flow", []),
        frontend_task_list=result.get("frontend_task_list", [])
    )
# ─────────────────────────────────────────────
# PDF / DOCX PARSER
# ─────────────────────────────────────────────

def ingest_document(project_id: str, blob_url: str) -> DocumentResult:
    raw = download_blob_bytes(blob_url)

    prompt = f"""
    I have a document. Here is its raw content (first 2000 chars):
    {raw[:2000].decode("utf-8", errors="ignore")}

    Return a JSON object with:
    - extracted_text: clean version of the text
    - user_stories: list of user story strings (format: As a X, I want Y, so that Z)
    - technical_constraints: list of technical constraint strings
    - key_value_pairs: dict of any key facts or metadata found

    Return JSON only, no explanation.
    """

    raw_response = call_gpt4o(prompt)

    try:
        clean = raw_response.strip().replace("```json", "").replace("```", "")
        result = json.loads(clean)
    except Exception:
        result = {
            "extracted_text": raw[:500].decode("utf-8", errors="ignore"),
            "user_stories": [],
            "technical_constraints": [],
            "key_value_pairs": {}
        }

    return DocumentResult(
        project_id=project_id,
        extracted_text=result.get("extracted_text", ""),
        user_stories=result.get("user_stories", []),
        technical_constraints=result.get("technical_constraints", []),
        key_value_pairs=result.get("key_value_pairs", {})
    )

# ─────────────────────────────────────────────
# MULTI FILE SYNTHESIZER
# ─────────────────────────────────────────────

def synthesize(project_id: str, results: list) -> UnifiedContext:
    csv_schema = next((r for r in results if isinstance(r, SchemaResult)), None)
    vision_result = next((r for r in results if isinstance(r, VisionResult)), None)
    document_result = next((r for r in results if isinstance(r, DocumentResult)), None)

    context_parts = []
    if csv_schema:
        context_parts.append(f"CSV Schema: domain={csv_schema.domain}, columns={csv_schema.columns}")
    if vision_result:
        context_parts.append(f"Wireframe: page={vision_result.page_name}, components={vision_result.components}")
    if document_result:
        context_parts.append(f"Document: user_stories={document_result.user_stories[:3]}")

    prompt = f"""
    Given these inputs from a project:
    {chr(10).join(context_parts)}

    Return a JSON object with:
    - combined_summary: 2-3 sentence summary of what this project is building
    - task_ledger_seeds: list of 5 specific development task strings to start with

    Return JSON only, no explanation.
    """

    raw_response = call_gpt4o(prompt)

    try:
        clean = raw_response.strip().replace("```json", "").replace("```", "")
        synthesis = json.loads(clean)
    except Exception:
        synthesis = {"combined_summary": "Could not synthesize", "task_ledger_seeds": []}

    return UnifiedContext(
        project_id=project_id,
        csv_schema=csv_schema,
        vision_result=vision_result,
        document_result=document_result,
        combined_summary=synthesis.get("combined_summary"),
        task_ledger_seeds=synthesis.get("task_ledger_seeds", [])
    )

# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "agent": "data-ingestion"}

@app.post("/ingest")
def ingest(request: IngestRequest):
    try:
        file_type = request.file_type.lower()

        if file_type == "csv":
            result = ingest_csv(request.project_id, request.blob_url)
        elif file_type == "json":
            result = ingest_json(request.project_id, request.blob_url)
        elif file_type == "openapi":
            result = ingest_openapi(request.project_id, request.blob_url)
        elif file_type == "png":
            result = ingest_image(request.project_id, request.blob_url)
        elif file_type in ["pdf", "docx"]:
            result = ingest_document(request.project_id, request.blob_url)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {file_type}")

        write_schema_result(result.dict())
        return {"status": "success", "result": result.dict()}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ingest-multi")
def ingest_multi(request: MultiIngestRequest):
    try:
        results = []
        for file in request.files:
            single = IngestRequest(
                project_id=request.project_id,
                blob_url=file.blob_url,
                file_type=file.file_type
            )
            response = ingest(single)
            file_type = file.file_type.lower()
            if file_type == "csv":
                results.append(SchemaResult(**response["result"]))
            elif file_type == "png":
                results.append(VisionResult(**response["result"]))
            elif file_type in ["pdf", "docx"]:
                results.append(DocumentResult(**response["result"]))

        if len(results) > 1:
            unified = synthesize(request.project_id, results)
            write_unified_context(unified.dict())
            return {"status": "success", "unified_context": unified.dict()}
        else:
            return {"status": "success", "result": results[0].dict() if results else {}}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))