from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional, Tuple


_BLOB_CONTAINER_CLIENT = None
_ENABLE_LOCAL_FILE_GENERATION = str(os.getenv("ENABLE_LOCAL_FILE_GENERATION", "false")).strip().lower() in {"1", "true", "yes", "on"}
_ENFORCE_AZURE_SOT = str(os.getenv("ENFORCE_AZURE_SOURCE_OF_TRUTH", "true")).strip().lower() in {"1", "true", "yes", "on"}


def _detect_repo_root() -> Path:
    env_root = (os.getenv("NEXUS_ROOT_DIR") or "").strip()
    if env_root:
        return Path(env_root).resolve()

    here = Path(__file__).resolve()
    if here.parent.name == "platform-backend" and here.parent.parent.name.startswith("Azure_Hack-"):
        return here.parent.parent.parent

    return here.parent


REPO_ROOT = _detect_repo_root()


def _workspace_roots() -> list[Path]:
    roots: list[Path] = []
    env_ws = (os.getenv("NEXUS_WORKSPACE_ROOT") or "").strip()
    if env_ws:
        roots.append(Path(env_ws).resolve())
    roots.append((REPO_ROOT / "workspace").resolve())

    # De-duplicate while preserving order
    dedup: list[Path] = []
    seen = set()
    for r in roots:
        key = str(r)
        if key in seen:
            continue
        seen.add(key)
        dedup.append(r)
    return dedup


def _generated_roots() -> list[Path]:
    roots = [
        (REPO_ROOT / "generated_code").resolve(),
        (Path(__file__).resolve().parent / "generated_code").resolve(),
    ]
    dedup: list[Path] = []
    seen = set()
    for r in roots:
        key = str(r)
        if key in seen:
            continue
        seen.add(key)
        dedup.append(r)
    return dedup


def _infer_project_id_from_path(local_path: Path) -> str:
    p = local_path.resolve()
    name = p.name

    # Known naming patterns in this backend
    for pattern in [
        r"^project_specs_(.+)\.md$",
        r"^ledger_(.+)\.json$",
        r"^project_(.+)_specs\.md$",
    ]:
        m = re.match(pattern, name)
        if m:
            candidate = str(m.group(1) or "").strip()
            if candidate:
                return candidate

    # Fallback: any path segment that looks like project-* id
    for part in p.parts:
        if re.fullmatch(r"project-[A-Za-z0-9._-]+", str(part)):
            return str(part)

    return ""


def _active_project_id(local_path: Optional[Path] = None) -> str:
    env_project = (os.getenv("NEXUS_ACTIVE_PROJECT_ID") or "").strip()
    if env_project:
        return env_project
    if local_path is not None:
        return _infer_project_id_from_path(local_path)
    return ""


def _blob_container_client():
    global _BLOB_CONTAINER_CLIENT
    if _BLOB_CONTAINER_CLIENT is not None:
        return _BLOB_CONTAINER_CLIENT

    conn = (os.getenv("AZURE_STORAGE_CONNECTION_STRING") or "").strip()
    if not conn:
        return None

    container = (os.getenv("AZURE_STORAGE_CONTAINER") or "project-workspace").strip() or "project-workspace"
    try:
        from azure.storage.blob import BlobServiceClient

        svc = BlobServiceClient.from_connection_string(conn)
        client = svc.get_container_client(container)
        try:
            client.create_container()
        except Exception:
            pass
        _BLOB_CONTAINER_CLIENT = client
        return _BLOB_CONTAINER_CLIENT
    except Exception:
        return None


def _map_local_to_blob(local_path: Path) -> Optional[str]:
    project_id = _active_project_id(local_path)
    if not project_id:
        return None

    p = local_path.resolve()
    for ws_root in _workspace_roots():
        try:
            rel = p.relative_to(ws_root).as_posix()
            return f"{project_id}/runtime/workspace/{rel}"
        except Exception:
            pass

    for gen_root in _generated_roots():
        try:
            rel = p.relative_to(gen_root).as_posix()
            return f"{project_id}/runtime/generated_code/{rel}"
        except Exception:
            pass

    return None


def upload_local_path_to_blob(local_path: str) -> Tuple[bool, str]:
    client = _blob_container_client()
    if client is None:
        return False, "Blob client unavailable"

    p = Path(local_path).resolve()
    if not p.exists() or not p.is_file():
        return False, f"Local file missing: {p}"

    blob_name = _map_local_to_blob(p)
    if not blob_name:
        return False, f"Path not mapped to runtime blob roots: {p}"

    try:
        with p.open("rb") as data:
            client.upload_blob(blob_name, data, overwrite=True)
        return True, blob_name
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def write_text_azure_first(local_path: str, content: str, materialize_local: Optional[bool] = None) -> Tuple[bool, str]:
    """Write file content to Azure first, then optionally materialize local copy.

    If ENFORCE_AZURE_SOURCE_OF_TRUTH=true and blob write fails, operation fails.
    """
    p = Path(local_path).resolve()
    blob_name = _map_local_to_blob(p)
    if not blob_name:
        return False, f"Path not mapped to runtime blob roots: {p}"

    client = _blob_container_client()
    if client is None:
        if _ENFORCE_AZURE_SOT:
            return False, "Blob client unavailable while ENFORCE_AZURE_SOURCE_OF_TRUTH=true"
    else:
        try:
            data = (content or "").encode("utf-8")
            client.upload_blob(blob_name, data, overwrite=True)
        except Exception as exc:
            if _ENFORCE_AZURE_SOT:
                return False, f"Azure-first write failed: {type(exc).__name__}: {exc}"

    if materialize_local is None:
        materialize_local = _ENABLE_LOCAL_FILE_GENERATION

    if materialize_local:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content or "", encoding="utf-8")
    else:
        # Keep local copy optional per source-of-truth policy.
        if p.exists() and p.is_file():
            try:
                p.unlink()
            except Exception:
                pass

    return True, blob_name


def download_blob_to_local_path(local_path: str) -> Tuple[bool, str]:
    client = _blob_container_client()
    if client is None:
        return False, "Blob client unavailable"

    p = Path(local_path).resolve()
    blob_name = _map_local_to_blob(p)
    if not blob_name:
        return False, f"Path not mapped to runtime blob roots: {p}"

    try:
        blob = client.download_blob(blob_name)
        data = blob.readall()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return True, blob_name
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def sync_blob_prefix_to_local_dir(local_dir: str) -> Tuple[bool, str]:
    client = _blob_container_client()
    if client is None:
        return False, "Blob client unavailable"

    local_root = Path(local_dir).resolve()
    project_id = _active_project_id(local_root)
    if not project_id:
        return False, "NEXUS_ACTIVE_PROJECT_ID not set"

    prefix = None
    for ws_root in _workspace_roots():
        try:
            rel = local_root.relative_to(ws_root).as_posix().strip("/")
            prefix = f"{project_id}/runtime/workspace/" + (f"{rel}/" if rel else "")
            break
        except Exception:
            pass

    if prefix is None:
        for gen_root in _generated_roots():
            try:
                rel = local_root.relative_to(gen_root).as_posix().strip("/")
                prefix = f"{project_id}/runtime/generated_code/" + (f"{rel}/" if rel else "")
                break
            except Exception:
                pass

    if prefix is None:
        return False, f"Directory not under runtime roots: {local_root}"

    try:
        count = 0
        for blob in client.list_blobs(name_starts_with=prefix):
            rel_path = blob.name[len(prefix):]
            if not rel_path:
                continue
            local_file = local_root / rel_path
            local_file.parent.mkdir(parents=True, exist_ok=True)
            local_file.write_bytes(client.download_blob(blob.name).readall())
            count += 1
        return True, f"synced {count} file(s) from {prefix}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def sync_local_dir_to_blob_prefix(local_dir: str) -> Tuple[bool, str]:
    client = _blob_container_client()
    if client is None:
        return False, "Blob client unavailable"

    local_root = Path(local_dir).resolve()
    project_id = _active_project_id(local_root)
    if not project_id:
        return False, "NEXUS_ACTIVE_PROJECT_ID not set"

    if not local_root.exists() or not local_root.is_dir():
        return False, f"Directory missing: {local_root}"

    prefix = None
    for ws_root in _workspace_roots():
        try:
            rel = local_root.relative_to(ws_root).as_posix().strip("/")
            prefix = f"{project_id}/runtime/workspace/" + (f"{rel}/" if rel else "")
            break
        except Exception:
            pass

    if prefix is None:
        for gen_root in _generated_roots():
            try:
                rel = local_root.relative_to(gen_root).as_posix().strip("/")
                prefix = f"{project_id}/runtime/generated_code/" + (f"{rel}/" if rel else "")
                break
            except Exception:
                pass

    if prefix is None:
        return False, f"Directory not under runtime roots: {local_root}"

    try:
        count = 0
        for root, _, files in os.walk(local_root):
            for name in files:
                full = Path(root) / name
                rel_path = full.relative_to(local_root).as_posix()
                blob_name = f"{prefix}{rel_path}"
                with full.open("rb") as data:
                    client.upload_blob(blob_name, data, overwrite=True)
                count += 1
        return True, f"uploaded {count} file(s) to {prefix}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
