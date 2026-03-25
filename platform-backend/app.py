import base64
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from fastapi import Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import backend_platform
from ingestion_service import build_ingestion_context


app = backend_platform.app


class CanvasUpdateRequest(BaseModel):
	canvas_data: Any


class ReferenceFileItem(BaseModel):
	filename: str
	url: str


class IngestionContextRequest(BaseModel):
	reference_files: List[ReferenceFileItem] = []
	include_canvas: bool = False


def _decode_jwt_payload(token: str) -> Dict[str, Any]:
	parts = (token or "").split(".")
	if len(parts) < 2:
		raise HTTPException(status_code=401, detail="Invalid bearer token")

	payload = parts[1]
	payload += "=" * (-len(payload) % 4)
	try:
		decoded = base64.urlsafe_b64decode(payload.encode("utf-8"))
		return json.loads(decoded.decode("utf-8"))
	except Exception as exc:
		raise HTTPException(status_code=401, detail="Unable to decode bearer token") from exc


def get_current_user(authorization: str = Header(default="")) -> Dict[str, Any]:
	if not authorization or not authorization.lower().startswith("bearer "):
		raise HTTPException(status_code=401, detail="Missing bearer token")

	token = authorization.split(" ", 1)[1].strip()
	payload = _decode_jwt_payload(token)
	user_id = payload.get("user_id") or payload.get("uid") or payload.get("sub")
	if not user_id:
		raise HTTPException(status_code=401, detail="Token missing user identifier")

	return {
		"uid": str(user_id),
		"email": payload.get("email"),
		"payload": payload,
	}


def assert_project_owner(project_id: str, current_user: Dict[str, Any]) -> Dict[str, Any]:
	project = backend_platform.store.get(project_id)
	if not project:
		raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

	owner_id = project.get("owner_id")
	if not owner_id:
		project["owner_id"] = current_user["uid"]
		backend_platform.store._save()
		return project

	if str(owner_id) != str(current_user["uid"]):
		raise HTTPException(status_code=403, detail="You do not have access to this project")

	return project


def _ensure_canvas_defaults() -> None:
	changed = False
	for project in backend_platform.store.projects.values():
		if "canvas_data" not in project:
			project["canvas_data"] = None
			changed = True
	if changed:
		backend_platform.store._save()


def _patch_project_create_with_canvas() -> None:
	if getattr(backend_platform.store, "_canvas_patch_applied", False):
		return

	original_create_with_id = backend_platform.store.create_with_id

	def create_with_canvas(project_id: str, project_name: str, user_intent: str, description: str | None):
		payload = original_create_with_id(project_id, project_name, user_intent, description)
		if "canvas_data" not in payload:
			payload["canvas_data"] = None
			backend_platform.store._save()
		return payload

	backend_platform.store.create_with_id = create_with_canvas
	backend_platform.store._canvas_patch_applied = True


def _safe_canvas_filename(name: str) -> str:
	candidate = Path(name or "").name.strip()
	if not candidate:
		raise HTTPException(status_code=400, detail="Filename is required")

	sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", candidate)
	if sanitized in {"", ".", ".."}:
		raise HTTPException(status_code=400, detail="Invalid filename")
	return sanitized


def _canvas_assets_dir(project_id: str) -> Path:
	return backend_platform.REPO_ROOT / "generated_code" / project_id / "canvas_assets"


_patch_project_create_with_canvas()
_ensure_canvas_defaults()


@app.get("/api/projects/{project_id}/canvas", tags=["Canvas"])
async def get_project_canvas(project_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
	project = assert_project_owner(project_id, current_user)
	return {"canvas_data": project.get("canvas_data")}


@app.put("/api/projects/{project_id}/canvas", tags=["Canvas"])
async def put_project_canvas(
	project_id: str,
	request: CanvasUpdateRequest,
	current_user: Dict[str, Any] = Depends(get_current_user),
):
	project = assert_project_owner(project_id, current_user)
	project["canvas_data"] = request.canvas_data
	project["updated_at"] = datetime.utcnow().isoformat()
	backend_platform.store._save()
	return {"canvas_data": project.get("canvas_data")}


@app.post("/api/projects/{project_id}/canvas/upload", tags=["Canvas"])
async def upload_project_canvas_file(
	project_id: str,
	file: UploadFile = File(...),
	current_user: Dict[str, Any] = Depends(get_current_user),
):
	assert_project_owner(project_id, current_user)

	filename = _safe_canvas_filename(file.filename or "")
	assets_dir = _canvas_assets_dir(project_id)
	assets_dir.mkdir(parents=True, exist_ok=True)

	target_path = assets_dir / filename
	content = await file.read()
	target_path.write_bytes(content)

	return {
		"url": f"/api/canvas-assets/{project_id}/{filename}",
		"filename": filename,
	}


@app.get("/api/canvas-assets/{project_id}/{filename:path}", tags=["Canvas"])
async def get_canvas_asset(project_id: str, filename: str):
	base = _canvas_assets_dir(project_id)
	candidate = (base / filename).resolve()
	try:
		candidate.relative_to(base.resolve())
	except Exception:
		raise HTTPException(status_code=403, detail="Access denied")

	if not candidate.exists() or not candidate.is_file():
		raise HTTPException(status_code=404, detail="Canvas asset not found")

	return FileResponse(candidate)


@app.post("/api/projects/{project_id}/ingestion/context", tags=["Ingestion"])
async def generate_project_ingestion_context(
	project_id: str,
	request: IngestionContextRequest,
	current_user: Dict[str, Any] = Depends(get_current_user),
):
	project = assert_project_owner(project_id, current_user)

	context = build_ingestion_context(
		repo_root=backend_platform.REPO_ROOT,
		project_id=project_id,
		reference_files=[item.model_dump() for item in request.reference_files],
		include_canvas=bool(request.include_canvas),
		canvas_data=project.get("canvas_data") if request.include_canvas else None,
	)

	project["ingestion_context"] = {
		"generated_at": context.get("generated_at"),
		"combined_summary": context.get("combined_summary"),
		"task_ledger_seeds": context.get("task_ledger_seeds") or [],
		"file_count": len(context.get("file_results") or []),
		"has_canvas": bool(context.get("canvas_result")),
		"persisted_files": context.get("persisted_files") or {},
	}
	project["updated_at"] = datetime.utcnow().isoformat()
	backend_platform.store._save()

	return context


__all__ = ["app", "get_current_user", "assert_project_owner"]
