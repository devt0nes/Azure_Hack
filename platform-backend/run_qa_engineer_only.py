#!/usr/bin/env python3
"""Run only QA Engineer from the latest (or specified) ledger in current workspace."""

import argparse
import contextlib
import glob
import os
import shutil
import traceback
from datetime import datetime
from typing import Dict

import agent_orchestrator_v3 as orchestrator_module
import general_agent as general_agent_module
from agent_orchestrator_v3 import EnhancedAgentOrchestrator, WORKSPACE_DIR


class _StreamToFile:
    """Simple stream sink that flushes every write."""

    def __init__(self, handle):
        self._handle = handle

    def write(self, data):
        self._handle.write(data)
        self._handle.flush()

    def flush(self):
        self._handle.flush()


def latest_ledger_id() -> str:
    ledger_files = sorted(
        [f for f in os.listdir(WORKSPACE_DIR) if f.startswith("ledger_") and f.endswith(".json")],
        reverse=True,
    )
    if not ledger_files:
        raise FileNotFoundError("No ledger_*.json found under workspace/")
    return ledger_files[0].replace("ledger_", "").replace(".json", "")


def seed_upstream_completed(orchestrator: EnhancedAgentOrchestrator) -> Dict[str, str]:
    """Mark upstream role outputs as completed using existing workspace directories."""
    candidates = {
        "system_architect": ["contracts", "docs/api"],
        "database_architect": ["database"],
        "backend_engineer": ["backend"],
        "frontend_engineer": ["frontend"],
    }

    seeded: Dict[str, str] = {}
    for role, rels in candidates.items():
        picked = None
        for rel in rels:
            abs_path = os.path.join(WORKSPACE_DIR, rel)
            if os.path.isdir(abs_path):
                picked = abs_path
                break
        if picked is None:
            picked = os.path.join(WORKSPACE_DIR, rels[0])
            os.makedirs(picked, exist_ok=True)
        orchestrator.completed_workspaces[role] = picked
        seeded[role] = picked
    return seeded


def clean_qa_artifacts(workspace_dir: str) -> None:
    targets = [
        os.path.join(workspace_dir, "qa"),
        os.path.join(workspace_dir, "tests"),
    ]
    for t in targets:
        if os.path.isdir(t):
            shutil.rmtree(t)

    files_to_remove = [
        os.path.join(workspace_dir, "notebooks", "qa_engineer.md"),
        os.path.join(workspace_dir, "layer_4_blackboard.md"),
    ]
    files_to_remove.extend(glob.glob(os.path.join(workspace_dir, "layer_issue_wake_*_4*.md")))

    for f in files_to_remove:
        if os.path.exists(f):
            os.remove(f)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run QA Engineer only")
    parser.add_argument("--ledger-id", default=None, help="Ledger id to use (default: latest)")
    parser.add_argument("--clean", action="store_true", help="Remove previous QA artifacts before run")
    parser.add_argument("--layer-timeout", type=int, default=0, help="Layer timeout seconds (0=no timeout)")
    parser.add_argument("--max-attempts", type=int, default=6, help="Max attempts for QA agent")
    parser.add_argument("--max-main-iterations", type=int, default=80, help="Max iterations for QA main run")
    parser.add_argument("--max-fix-iterations", type=int, default=45, help="Max iterations for QA fix-mode")
    parser.add_argument(
        "--wake-assigned",
        action="store_true",
        help="After QA completes, run issue-wake cycles for roles assigned new QA issues",
    )
    parser.add_argument("--model-delay-min", type=float, default=0.15, help="Min model delay seconds")
    parser.add_argument("--model-delay-max", type=float, default=0.5, help="Max model delay seconds")
    parser.add_argument("--log-file", default=None, help="Log file path (default: ./logs)")
    args = parser.parse_args()

    ledger_id = args.ledger_id or latest_ledger_id()

    repo_root = os.path.dirname(os.path.abspath(__file__))
    logs_dir = os.path.join(repo_root, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = args.log_file or os.path.join(logs_dir, f"qa_only_{ledger_id}_{timestamp}.log")

    print(f"📝 Writing QA-only output to: {log_file}")

    with open(log_file, "w", encoding="utf-8") as lf:
        sink = _StreamToFile(lf)
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            try:
                print(f"📋 Using ledger: {ledger_id}")

                if args.clean:
                    print("🧹 Cleaning previous QA artifacts...")
                    clean_qa_artifacts(WORKSPACE_DIR)

                orchestrator_module.LAYER_MAX_WAIT_SECONDS = int(args.layer_timeout) if int(args.layer_timeout) > 0 else 0
                orchestrator_module.AGENT_MAX_ATTEMPTS = max(1, int(args.max_attempts))
                orchestrator_module.AGENT_MAX_ITERATIONS_MAIN = max(10, int(args.max_main_iterations))
                orchestrator_module.AGENT_MAX_ITERATIONS_FIX = max(5, int(args.max_fix_iterations))
                general_agent_module.MODEL_CALL_DELAY_MIN = max(0.0, float(args.model_delay_min))
                general_agent_module.MODEL_CALL_DELAY_MAX = max(
                    general_agent_module.MODEL_CALL_DELAY_MIN,
                    float(args.model_delay_max),
                )

                orchestrator = EnhancedAgentOrchestrator(ledger_id)
                orchestrator._require_global_contract()

                seeded = seed_upstream_completed(orchestrator)
                print("✅ Seeded upstream completed roles:")
                for role, path in seeded.items():
                    print(f"  - {role}: {path}")

                qa_spec = orchestrator._get_agent_spec("qa_engineer")
                if not qa_spec:
                    raise RuntimeError("Missing qa_engineer spec in ledger")

                print("\n🚀 Running targeted QA Engineer...")
                orchestrator.execute_layer(
                    layer_index=3,
                    agents_in_layer=[qa_spec],
                    total_layers=1,
                    layer_blackboard_path=os.path.join(WORKSPACE_DIR, "layer_4_blackboard.md"),
                    phase_label="TARGETED QA ONLY",
                )

                if args.wake_assigned:
                    print("\n🔔 Running issue wake cycle for roles assigned by QA...")
                    woken = orchestrator._run_issue_wake_cycle(trigger="qa_only")
                    print(f"✅ Wake cycle complete. Agents woken: {woken}")

                print("\n✅ QA-only run completed.")
                return 0
            except Exception:
                traceback.print_exc()
                return 1


if __name__ == "__main__":
    raise SystemExit(main())
