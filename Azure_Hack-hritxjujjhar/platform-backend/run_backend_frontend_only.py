#!/usr/bin/env python3
"""Run only backend_engineer + frontend_engineer from the latest ledger.

This avoids rerunning the full pipeline when Layer 3 fails.
"""

import argparse
import os
import shutil
import glob
import sys
import traceback
import contextlib
from datetime import datetime
from typing import Dict

import agent_orchestrator_v3 as orchestrator_module
import general_agent as general_agent_module
from blob_workspace import build_blob_workspace_from_env
from agent_orchestrator_v3 import EnhancedAgentOrchestrator, WORKSPACE_DIR


def latest_ledger_id() -> str:
    ledger_files = sorted(
        [f for f in os.listdir(WORKSPACE_DIR) if f.startswith("ledger_") and f.endswith(".json")],
        reverse=True,
    )
    if not ledger_files:
        raise FileNotFoundError("No ledger_*.json found under workspace/")
    return ledger_files[0].replace("ledger_", "").replace(".json", "")


def clean_backend_frontend_artifacts(workspace_dir: str) -> None:
    targets = [
        os.path.join(workspace_dir, "backend"),
        os.path.join(workspace_dir, "frontend"),
    ]
    for t in targets:
        if os.path.isdir(t):
            shutil.rmtree(t)

    files_to_remove = [
        os.path.join(workspace_dir, "blackboard.md"),
        os.path.join(workspace_dir, "notebooks", "backend_engineer.md"),
        os.path.join(workspace_dir, "notebooks", "frontend_engineer.md"),
    ]
    files_to_remove.extend(glob.glob(os.path.join(workspace_dir, "layer_3*.md")))
    files_to_remove.extend(glob.glob(os.path.join(workspace_dir, "layer_iteration2_3*.md")))

    for f in files_to_remove:
        if os.path.exists(f):
            os.remove(f)


def seed_upstream_completed(orchestrator: EnhancedAgentOrchestrator) -> Dict[str, str]:
    # Seed required upstream roles so targeted Layer 3 can execute standalone.
    # Paths reflect expected production roots from this workspace.
    seeded = {
        "api_designer": os.path.join(WORKSPACE_DIR, "contracts"),
        "database_architect": os.path.join(WORKSPACE_DIR, "database", "schema"),
        "security_engineer": os.path.join(WORKSPACE_DIR, "security"),
    }

    for role, path in seeded.items():
        os.makedirs(path, exist_ok=True)
        orchestrator.completed_workspaces[role] = path

    return seeded


class _StreamToFile:
    """Simple text stream writer for redirecting stdout/stderr to a log file."""

    def __init__(self, handle):
        self._handle = handle

    def write(self, data):
        self._handle.write(data)
        self._handle.flush()

    def flush(self):
        self._handle.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run only backend/frontend agents from ledger")
    parser.add_argument("--layer-timeout", type=int, default=900, help="Layer timeout seconds for targeted execution")
    parser.add_argument("--max-attempts", type=int, default=6, help="Max attempts per agent in targeted run")
    parser.add_argument("--max-main-iterations", type=int, default=75, help="Max iterations for main agent run")
    parser.add_argument("--max-fix-iterations", type=int, default=45, help="Max iterations for fix-mode runs")
    parser.add_argument("--model-delay-min", type=float, default=0.15, help="Min per-iteration model-call delay seconds")
    parser.add_argument("--model-delay-max", type=float, default=0.5, help="Max per-iteration model-call delay seconds")
    parser.add_argument("--project-id", default=None, help="Optional project id prefix for Azure Blob workspace sync")
    parser.add_argument("--log-file", default=None, help="Path to execution log file (default: ./logs/)")
    args = parser.parse_args()

    # Always run against the latest available ledger.
    ledger_id = latest_ledger_id()

    # Logs are stored at repository root (not under workspace/).
    repo_root = os.path.dirname(os.path.abspath(__file__))
    logs_dir = os.path.join(repo_root, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = args.log_file or os.path.join(logs_dir, f"backend_frontend_only_{ledger_id}_{timestamp}.log")

    print(f"📝 Writing targeted-run output to: {log_file}")

    with open(log_file, "w", encoding="utf-8") as lf:
        sink = _StreamToFile(lf)
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            try:
                print(f"📋 Using ledger: {ledger_id}")

                blob = None
                project_id = args.project_id
                try:
                    blob = build_blob_workspace_from_env()
                except Exception as exc:
                    print(f"⚠️ Blob workspace unavailable: {exc}")

                if blob and project_id:
                    print(f"☁️ Syncing workspace from blob (project_id={project_id})...")
                    downloaded = blob.download_project(project_id, WORKSPACE_DIR)
                    print(f"☁️ Downloaded {downloaded} files from blob container")

                print("🧹 Cleaning backend/frontend artifacts, related blackboards, and notebooks...")
                clean_backend_frontend_artifacts(WORKSPACE_DIR)

                # Allow targeted runs to tune timeout behavior without editing orchestrator defaults.
                orchestrator_module.LAYER_MAX_WAIT_SECONDS = max(60, int(args.layer_timeout))
                orchestrator_module.AGENT_MAX_ATTEMPTS = max(1, int(args.max_attempts))
                orchestrator_module.AGENT_MAX_ITERATIONS_MAIN = max(10, int(args.max_main_iterations))
                orchestrator_module.AGENT_MAX_ITERATIONS_FIX = max(5, int(args.max_fix_iterations))
                general_agent_module.MODEL_CALL_DELAY_MIN = max(0.0, float(args.model_delay_min))
                general_agent_module.MODEL_CALL_DELAY_MAX = max(
                    general_agent_module.MODEL_CALL_DELAY_MIN,
                    float(args.model_delay_max),
                )

                orchestrator = EnhancedAgentOrchestrator(ledger_id)

                # Make sure contract exists and is valid before targeted run.
                orchestrator._require_global_contract()

                seeded = seed_upstream_completed(orchestrator)
                print("✅ Seeded upstream completed roles:")
                for role, path in seeded.items():
                    print(f"  - {role}: {path}")

                backend_spec = orchestrator._get_agent_spec("backend_engineer")
                frontend_spec = orchestrator._get_agent_spec("frontend_engineer")
                if not backend_spec or not frontend_spec:
                    raise RuntimeError("Missing backend_engineer or frontend_engineer spec in ledger")

                print("\n🚀 Running targeted backend + frontend roles in parallel...")
                orchestrator.execute_layer(
                    layer_index=2,
                    agents_in_layer=[backend_spec, frontend_spec],
                    total_layers=2,
                    layer_blackboard_path=os.path.join(WORKSPACE_DIR, "layer_3_blackboard.md"),
                    phase_label="TARGETED BACKEND+FRONTEND",
                )

                if blob and project_id:
                    print(f"☁️ Uploading workspace to blob (project_id={project_id})...")
                    uploaded = blob.upload_project(project_id, WORKSPACE_DIR)
                    print(f"☁️ Uploaded {uploaded} files to blob container")

                print("\n✅ Targeted backend/frontend run completed.")
                return 0
            except Exception:
                traceback.print_exc()
                return 1


if __name__ == "__main__":
    raise SystemExit(main())
