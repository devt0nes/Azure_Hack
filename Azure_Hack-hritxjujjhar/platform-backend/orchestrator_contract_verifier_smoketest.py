#!/usr/bin/env python3
"""Smoke test for orchestrator contract-verification fixes.

This validates that:
1) Contract routes are loaded from current contract file.
2) Backend routes are detected from app.use(routerVar) style mounts.
3) Frontend API calls are detected from handleFetch()/BASE_URL template usage.
4) Contract alignment checks pass for both backend and frontend.

Run:
  python3 orchestrator_contract_verifier_smoketest.py
"""

import os
import sys
from pprint import pprint

import agent_orchestrator_v3 as orchestrator_module
from agent_orchestrator_v3 import EnhancedAgentOrchestrator


def main() -> int:
    repo_root = os.path.dirname(os.path.abspath(__file__))
    workspace_dir = os.path.join(repo_root, "workspace")
    backend_ws = os.path.join(workspace_dir, "backend")
    frontend_ws = os.path.join(workspace_dir, "frontend")

    # Force orchestrator helpers to resolve contract from this workspace.
    orchestrator_module.WORKSPACE_DIR = workspace_dir

    orch = EnhancedAgentOrchestrator.__new__(EnhancedAgentOrchestrator)

    print("== Orchestrator Contract Verifier Smoke Test ==")
    print(f"Workspace: {workspace_dir}")

    contract = orch._load_contract_routes()
    if not contract.get("ok"):
        print("❌ Contract load failed:")
        print(contract.get("error"))
        return 1

    contract_routes = {orch._canonical_route_key(r) for r in set(contract.get("routes", {}).keys())}
    print(f"Contract routes discovered: {len(contract_routes)}")

    backend = orch._collect_backend_routes(backend_ws)
    if not backend.get("ok"):
        print("❌ Backend route collection failed:")
        print(backend.get("error"))
        return 1
    backend_routes = {orch._canonical_route_key(r) for r in set(backend.get("routes", set()))}
    print(f"Backend routes discovered:  {len(backend_routes)}")

    frontend = orch._collect_frontend_api_calls(frontend_ws)
    if not frontend.get("ok"):
        print("❌ Frontend API call collection failed:")
        print(frontend.get("error"))
        return 1
    frontend_routes = {orch._canonical_route_key(r) for r in set(frontend.get("routes", set()))}
    print(f"Frontend routes discovered: {len(frontend_routes)}")

    missing_backend = sorted(contract_routes - backend_routes)
    extra_backend = sorted(backend_routes - contract_routes)

    # Frontend static parsing cannot reliably infer semantic param names from template variables,
    # so mirror orchestrator's loose-param comparison for frontend only.
    contract_frontend_loose = {orch._canonical_route_key_loose_params(r) for r in contract_routes}
    frontend_routes_loose = {orch._canonical_route_key_loose_params(r) for r in frontend_routes}
    missing_frontend = sorted(contract_frontend_loose - frontend_routes_loose)
    extra_frontend = sorted(frontend_routes_loose - contract_frontend_loose)

    print("\nBackend alignment: ", "PASS" if not missing_backend and not extra_backend else "FAIL")
    if missing_backend:
        print("  Missing backend routes:")
        pprint(missing_backend)
    if extra_backend:
        print("  Non-contract backend routes:")
        pprint(extra_backend)

    print("Frontend alignment:", "PASS" if not missing_frontend and not extra_frontend else "FAIL")
    if missing_frontend:
        print("  Missing frontend routes:")
        pprint(missing_frontend)
    if extra_frontend:
        print("  Non-contract frontend calls:")
        pprint(extra_frontend)

    # Double-check through orchestrator's integrated verifier methods.
    integrated_backend = orch._verify_contract_alignment("backend_engineer", backend_ws)
    integrated_frontend = orch._verify_contract_alignment("frontend_engineer", frontend_ws)

    print("\nIntegrated backend verifier:", "PASS" if integrated_backend.get("ok") else "FAIL")
    if not integrated_backend.get("ok"):
        pprint(integrated_backend.get("missing", []))

    print("Integrated frontend verifier:", "PASS" if integrated_frontend.get("ok") else "FAIL")
    if not integrated_frontend.get("ok"):
        pprint(integrated_frontend.get("missing", []))

    ok = (
        not missing_backend
        and not extra_backend
        and not missing_frontend
        and not extra_frontend
        and integrated_backend.get("ok")
        and integrated_frontend.get("ok")
    )

    if ok:
        print("\n✅ Smoke test passed: verifier fixes are working on current generated code.")
        return 0

    print("\n❌ Smoke test failed: alignment or verifier still mismatched.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
