#!/usr/bin/env python3
"""Sync project runtime workspace to/from Azure Blob Storage.

This utility is intended for containerized command execution where `/app/workspace`
must be hydrated from blob before command execution and uploaded back afterward.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Tuple


def _blob_container_client():
    conn = (os.getenv("AZURE_STORAGE_CONNECTION_STRING") or "").strip()
    if not conn:
        return None, "AZURE_STORAGE_CONNECTION_STRING is missing"

    container_name = (os.getenv("AZURE_STORAGE_CONTAINER") or "project-workspace").strip() or "project-workspace"
    try:
        from azure.storage.blob import BlobServiceClient  # type: ignore

        svc = BlobServiceClient.from_connection_string(conn)
        return svc.get_container_client(container_name), ""
    except Exception as exc:
        return None, f"Failed to initialize blob client: {type(exc).__name__}: {exc}"


def _download_workspace(project_id: str, workspace_dir: Path, prefix: str = "runtime/workspace") -> Tuple[bool, str]:
    client, err = _blob_container_client()
    if client is None:
        return False, err

    blob_prefix = f"{project_id}/{prefix.strip('/')}/"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    try:
        for blob in client.list_blobs(name_starts_with=blob_prefix):
            rel = blob.name[len(blob_prefix):]
            if not rel:
                continue
            out_file = workspace_dir / rel
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(client.download_blob(blob.name).readall())
            count += 1
        return True, f"downloaded {count} blob file(s) from {blob_prefix}"
    except Exception as exc:
        return False, f"Download failed: {type(exc).__name__}: {exc}"


def _upload_workspace(project_id: str, workspace_dir: Path, prefix: str = "runtime/workspace") -> Tuple[bool, str]:
    client, err = _blob_container_client()
    if client is None:
        return False, err
    if not workspace_dir.exists():
        return False, f"Workspace directory does not exist: {workspace_dir}"

    blob_prefix = f"{project_id}/{prefix.strip('/')}/"
    count = 0
    try:
        for root, _, files in os.walk(workspace_dir):
            for name in files:
                full = Path(root) / name
                rel = full.relative_to(workspace_dir).as_posix()
                with full.open("rb") as fh:
                    client.upload_blob(f"{blob_prefix}{rel}", fh, overwrite=True)
                count += 1
        return True, f"uploaded {count} blob file(s) to {blob_prefix}"
    except Exception as exc:
        return False, f"Upload failed: {type(exc).__name__}: {exc}"


def _upload_dist_to_web(project_id: str, dist_dir: Path) -> Tuple[bool, str]:
    conn = (os.getenv("AZURE_STORAGE_CONNECTION_STRING") or "").strip()
    if not conn:
        return False, "AZURE_STORAGE_CONNECTION_STRING is missing"
    if not dist_dir.exists() or not dist_dir.is_dir():
        return False, f"Dist directory not found: {dist_dir}"

    try:
        from azure.storage.blob import BlobServiceClient  # type: ignore

        svc = BlobServiceClient.from_connection_string(conn)
        web = svc.get_container_client("$web")
        try:
            web.create_container()
        except Exception:
            pass

        count = 0
        for root, _, files in os.walk(dist_dir):
            for name in files:
                full = Path(root) / name
                rel = full.relative_to(dist_dir).as_posix()
                blob_name = f"{project_id}/frontend/dist/{rel}"
                with full.open("rb") as fh:
                    web.upload_blob(blob_name, fh, overwrite=True)
                count += 1
        return True, f"uploaded {count} file(s) to $web/{project_id}/frontend/dist/"
    except Exception as exc:
        return False, f"$web upload failed: {type(exc).__name__}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Azure Blob workspace sync utility")
    parser.add_argument("--mode", required=True, choices=["download", "upload", "upload-dist-web"])
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--workspace", default="/app/workspace")
    parser.add_argument("--dist-relative", default="frontend/dist")
    args = parser.parse_args()

    project_id = str(args.project_id or "").strip()
    workspace = Path(args.workspace).resolve()

    if not project_id:
        print("ERROR: --project-id is required", file=sys.stderr)
        return 2

    if args.mode == "download":
        ok, detail = _download_workspace(project_id, workspace)
    elif args.mode == "upload":
        ok, detail = _upload_workspace(project_id, workspace)
    else:
        dist_dir = (workspace / str(args.dist_relative)).resolve()
        ok, detail = _upload_dist_to_web(project_id, dist_dir)

    stream = sys.stdout if ok else sys.stderr
    print(detail, file=stream, flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
