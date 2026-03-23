import os
import uvicorn

from backend_platform import app


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    reload_enabled = str(os.getenv("BACKEND_RELOAD", "false")).lower() in {"1", "true", "yes"}
    uvicorn.run("backend_platform:app", host="0.0.0.0", port=port, reload=reload_enabled)
