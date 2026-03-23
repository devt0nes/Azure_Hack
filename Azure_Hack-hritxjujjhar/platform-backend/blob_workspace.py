import os
from pathlib import Path
from typing import Optional


class BlobWorkspace:
    """Sync project workspaces to/from Azure Blob Storage.

    Blob layout:
      <project_id>/<relative_path>
    """

    def __init__(self, connection_string: str, container: str = "workspace"):
        try:
            from azure.storage.blob import BlobServiceClient  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "azure-storage-blob is not installed. Install it to enable blob sync."
            ) from exc

        self.client = BlobServiceClient.from_connection_string(connection_string)
        self.container = self.client.get_container_client(container)
        try:
            self.container.create_container()
        except Exception:
            # Container already exists or no permission. Ignore for idempotency.
            pass

    def download_project(self, project_id: str, local_path: str) -> int:
        prefix = f"{project_id}/"
        local_root = Path(local_path)
        local_root.mkdir(parents=True, exist_ok=True)

        count = 0
        for blob in self.container.list_blobs(name_starts_with=prefix):
            rel_path = blob.name[len(prefix):]
            if not rel_path:
                continue
            local_file = local_root / rel_path
            local_file.parent.mkdir(parents=True, exist_ok=True)
            data = self.container.download_blob(blob.name).readall()
            local_file.write_bytes(data)
            count += 1
        return count

    def upload_project(self, project_id: str, local_path: str) -> int:
        local_root = Path(local_path)
        if not local_root.exists():
            return 0

        count = 0
        for root, _, files in os.walk(local_root):
            for name in files:
                full_path = Path(root) / name
                rel_path = full_path.relative_to(local_root).as_posix()
                blob_name = f"{project_id}/{rel_path}"
                with open(full_path, "rb") as data:
                    self.container.upload_blob(blob_name, data, overwrite=True)
                count += 1
        return count


def build_blob_workspace_from_env() -> Optional[BlobWorkspace]:
    conn = (os.getenv("AZURE_STORAGE_CONNECTION_STRING") or "").strip()
    if not conn:
        return None
    container = (os.getenv("AZURE_STORAGE_CONTAINER") or "workspace").strip() or "workspace"
    return BlobWorkspace(conn, container=container)
