"""
review_agent.py - Automated review agent for second development iteration

Scans generated agent workspaces, records issues into shared issues tracker,
and marks which agent must wake up to fix each issue.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Dict, List

from issues_tracker import get_issues_tracker


class ReviewAgent:
    """Deterministic reviewer that raises actionable issues for specific agents."""

    def __init__(self, workspace_dir: str = "./workspace"):
        self.workspace_dir = workspace_dir
        self.issues_tracker = get_issues_tracker()
        self.ledger = self._load_latest_ledger()
        self.requirements_text = self._build_requirements_text()

    def _path(self, *parts: str) -> str:
        return os.path.join(self.workspace_dir, *parts)

    def _exists(self, rel_path: str) -> bool:
        return os.path.exists(self._path(*rel_path.split("/")))

    def _read(self, rel_path: str) -> str:
        p = self._path(*rel_path.split("/"))
        if not os.path.exists(p):
            return ""
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return ""

    def _read_first(self, candidates: List[str]) -> str:
        """Read first existing file from candidates, else empty."""
        for rel in candidates:
            if self._exists(rel):
                return self._read(rel)
        return ""

    def _load_latest_ledger(self) -> Dict:
        """Load most recent ledger_*.json if available."""
        try:
            if not os.path.isdir(self.workspace_dir):
                return {}
            candidates = [
                os.path.join(self.workspace_dir, name)
                for name in os.listdir(self.workspace_dir)
                if name.startswith("ledger_") and name.endswith(".json")
            ]
            if not candidates:
                return {}
            latest = max(candidates, key=os.path.getmtime)
            with open(latest, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _build_requirements_text(self) -> str:
        """Flatten key ledger requirement fields into searchable lowercase text."""
        try:
            if not isinstance(self.ledger, dict):
                return ""
            parts = []
            for key in ["user_intent", "project_name", "project_description", "timeline_budget"]:
                val = self.ledger.get(key)
                if isinstance(val, str) and val.strip():
                    parts.append(val)

            for key in ["functional_requirements", "feature_catalog", "integration_targets"]:
                val = self.ledger.get(key)
                if isinstance(val, list):
                    parts.extend([str(v) for v in val if isinstance(v, (str, int, float))])

            return "\n".join(parts).lower()
        except Exception:
            return ""

    def _ledger_has_any(self, keywords: List[str]) -> bool:
        """Return True only when at least one keyword exists in ledger requirements text."""
        hay = self.requirements_text or ""
        if not hay:
            return False
        return any(str(k).lower() in hay for k in keywords)

    def _report(self, component: str, description: str, assigned_to: str, severity: str = "HIGH", tried: str = "") -> Dict:
        return self.issues_tracker.report_issue(
            component=component,
            description=description,
            severity=severity,
            reported_by="review_agent",
            assigned_to=assigned_to,
            tried=tried,
            context={"source": "second_iteration_review"}
        )

    def _first_existing(self, candidates: List[str]) -> str:
        """Return first existing relative path from candidates, else empty string."""
        for rel in candidates:
            if self._exists(rel):
                return rel
        return ""

    def _path_exists_for_import(self, base_dir: str, import_path: str) -> bool:
        """Resolve JS import path candidates and check if any exists."""
        if not import_path.startswith("."):
            return True  # external package import

        norm_base = base_dir.replace("\\", "/").strip("/")
        target = os.path.normpath(os.path.join(norm_base, import_path)).replace("\\", "/")
        candidates = [
            target,
            f"{target}.js",
            f"{target}.jsx",
            f"{target}.ts",
            f"{target}.tsx",
            f"{target}/index.js",
            f"{target}/index.jsx",
            f"{target}/index.ts",
            f"{target}/index.tsx",
        ]
        return any(self._exists(c) for c in candidates)

    def _check_local_import_paths(self, rel_path: str, assigned_to: str, severity: str = "HIGH"):
        """Check require()/import paths in a JS/TS file for unresolved local modules."""
        content = self._read(rel_path)
        if not content:
            return

        base_dir = os.path.dirname(rel_path)
        require_paths = re.findall(r"require\(\s*['\"]([^'\"]+)['\"]\s*\)", content)
        import_paths = re.findall(r"from\s+['\"]([^'\"]+)['\"]", content)

        unresolved = []
        for imp in require_paths + import_paths:
            if imp.startswith(".") and not self._path_exists_for_import(base_dir, imp):
                unresolved.append(imp)

        if unresolved:
            uniq = sorted(set(unresolved))
            self._report(
                component=rel_path,
                description=f"Unresolved local imports detected: {', '.join(uniq)}",
                assigned_to=assigned_to,
                severity=severity
            )

    def _check_readme_presence(self, role: str):
        role_readme_candidates = {
            "database_architect": ["database/README.md", "database/schemas/README.md", "database_architect/README.md"],
            "security_engineer": ["security/README.md", "security/policies/README.md", "security_engineer/README.md"],
            "backend_engineer": ["backend/README.md", "backend/src/README.md", "backend_engineer/README.md"],
            "frontend_engineer": ["frontend/README.md", "frontend/src/README.md", "frontend_engineer/README.md"],
            "qa_engineer": ["tests/README.md", "tests/reports/README.md", "qa_engineer/README.md"],
        }
        candidates = role_readme_candidates.get(role, [f"{role}/README.md"])
        if not any(self._exists(path) for path in candidates):
            self._report(
                component=f"{role} README",
                description="README.md missing. Add setup, architecture, generated files summary, and usage notes.",
                assigned_to=role,
                severity="MEDIUM"
            )

    def _check_frontend_backend_api_alignment(self):
        api_js = self._read_first([
            "frontend/src/utils/api.js",
            "frontend_engineer/src/utils/api.js",
        ])
        app_js = self._read_first([
            "backend/src/app.js",
            "backend/app.js",
            "backend_engineer/app.js",
        ])
        product_routes_rel = self._first_existing([
            "backend/src/routes/productRoutes.js",
            "backend/src/routes/catalogRoutes.js",
            "backend/src/routes/product.js",
            "backend/src/routes/catalog.js",
            "backend/routes/productRoutes.js",
            "backend/routes/catalogRoutes.js",
            "backend/routes/product.js",
            "backend/routes/catalog.js",
            "backend_engineer/routes/productRoutes.js",
            "backend_engineer/routes/catalogRoutes.js",
            "backend_engineer/routes/product.js",
            "backend_engineer/routes/catalog.js"
        ])
        cart_routes_rel = self._first_existing([
            "backend/src/routes/cartRoutes.js",
            "backend/src/routes/cart.js",
            "backend/routes/cartRoutes.js",
            "backend/routes/cart.js",
            "backend_engineer/routes/cartRoutes.js",
            "backend_engineer/routes/cart.js"
        ])

        if not api_js or not app_js:
            return

        # Frontend uses /api prefix by default in generated output.
        frontend_uses_api_prefix = "/api" in api_js
        backend_has_api_prefix = "app.use('/api" in app_js or 'app.use("/api' in app_js
        if frontend_uses_api_prefix and not backend_has_api_prefix:
            self._report(
                component="frontend-backend API base path",
                description=(
                    "Frontend API utility uses '/api' prefix but backend app.js does not mount routes under '/api'. "
                    "Align API base path on one side."
                ),
                assigned_to="backend_engineer",
                severity="HIGH"
            )
            self._report(
                component="frontend-backend API base path",
                description="Frontend API base URL likely mismatched with backend route mount. Confirm and align base path.",
                assigned_to="frontend_engineer",
                severity="HIGH"
            )

        # Route presence checks for endpoints used by frontend.
        product_expected = "/products" in api_js or self._ledger_has_any(["product", "catalog", "inventory"])
        if product_expected and not product_routes_rel:
            self._report(
                component="backend routes/products",
                description="Frontend expects product endpoints but backend product routes file is missing.",
                assigned_to="backend_engineer",
                severity="HIGH"
            )

        cart_expected = "/cart" in api_js or self._ledger_has_any(["cart", "shopping cart"])
        if cart_expected and not cart_routes_rel:
            self._report(
                component="backend routes/cart",
                description="Frontend expects cart endpoints but backend cart routes file is missing.",
                assigned_to="backend_engineer",
                severity="HIGH"
            )

    def _check_schema_order(self):
        if not self._ledger_has_any(["product", "catalog", "inventory", "category"]):
            return
        schema = self._read_first([
            "database/schemas/schema.sql",
            "database/migrations/schema.sql",
            "database_architect/migrations/schema.sql",
        ])
        if not schema:
            return

        products_idx = schema.find("CREATE TABLE products")
        categories_idx = schema.find("CREATE TABLE categories")
        if products_idx != -1 and categories_idx != -1 and products_idx < categories_idx and "REFERENCES categories" in schema:
            self._report(
                component="database schema FK ordering",
                description="products table references categories before categories is created. Reorder DDL to avoid migration failure.",
                assigned_to="database_architect",
                severity="HIGH"
            )

    def _check_security(self):
        validation = self._read_first([
            "security/middleware/validation.js",
            "security_engineer/middleware/validation.js",
        ])
        if validation and validation.strip().endswith("/[<>\\"):
            self._report(
                component="security validation middleware",
                description="validation.js appears truncated/invalid. Implement complete sanitize/validate middleware.",
                assigned_to="security_engineer",
                severity="CRITICAL"
            )

        sec_pkg = self._read_first([
            "security/package.json",
            "security_engineer/package.json",
        ])
        if '"crypto"' in sec_pkg:
            self._report(
                component="security package dependencies",
                description="Remove deprecated npm 'crypto' package; use built-in Node crypto module.",
                assigned_to="security_engineer",
                severity="MEDIUM"
            )

    def _check_qa_paths(self):
        qa_tests = [
            "tests/unit.test.js",
            "tests/integration.test.js",
            "tests/backend.test.js",
            "tests/frontend.test.js",
            "tests/database.test.js",
            "tests/e2e.test.js",
            "tests/reports/unit.test.js",
            "tests/reports/integration.test.js",
            "tests/reports/backend.test.js",
            "tests/reports/frontend.test.js",
            "tests/reports/database.test.js",
            "tests/reports/e2e.test.js",
            "qa_engineer/tests/unit.test.js",
            "qa_engineer/tests/integration.test.js",
            "qa_engineer/tests/backend.test.js",
            "qa_engineer/tests/frontend.test.js",
            "qa_engineer/tests/database.test.js",
            "qa_engineer/tests/e2e.test.js",
        ]
        for test_file in qa_tests:
            if self._exists(test_file):
                self._check_local_import_paths(test_file, assigned_to="qa_engineer", severity="HIGH")

    def _check_backend_imports(self):
        backend_files = [
            "backend/src/app.js",
            "backend/src/routes/productRoutes.js",
            "backend/src/routes/cartRoutes.js",
            "backend/src/controllers/productController.js",
            "backend/src/controllers/cartController.js",
            "backend/app.js",
            "backend/routes/productRoutes.js",
            "backend/routes/cartRoutes.js",
            "backend/controllers/productController.js",
            "backend/controllers/cartController.js",
            "backend_engineer/app.js",
            "backend_engineer/routes/productRoutes.js",
            "backend_engineer/routes/cartRoutes.js",
            "backend_engineer/controllers/productController.js",
            "backend_engineer/controllers/cartController.js",
        ]
        for f in backend_files:
            if self._exists(f):
                self._check_local_import_paths(f, assigned_to="backend_engineer", severity="HIGH")

    def _check_checkout_completeness(self):
        if not self._ledger_has_any(["checkout", "payment", "cart", "order"]):
            return
        # Functional requirement includes checkout flow; ensure backend has corresponding implementation artifacts.
        checkout_route_exists = self._first_existing([
            "backend/src/routes/checkoutRoutes.js",
            "backend/src/routes/checkout.js",
            "backend/routes/checkoutRoutes.js",
            "backend/routes/checkout.js",
            "backend_engineer/routes/checkoutRoutes.js",
            "backend_engineer/routes/checkout.js"
        ])
        checkout_controller_exists = self._first_existing([
            "backend/src/controllers/checkoutController.js",
            "backend/controllers/checkoutController.js",
            "backend_engineer/controllers/checkoutController.js"
        ])
        if not checkout_route_exists or not checkout_controller_exists:
            self._report(
                component="backend checkout flow",
                description="Checkout route/controller appears incomplete or missing; implement full checkout backend flow.",
                assigned_to="backend_engineer",
                severity="MEDIUM"
            )

    def _write_review_report(self, created_issues: List[Dict]):
        report_path = self._path("review_report.md")
        lines = [
            "# Review Agent Report",
            "",
            f"Total issues created: {len(created_issues)}",
            "",
            "## Issues"
        ]
        for issue in created_issues:
            lines.extend([
                f"- [{issue['severity']}] #{issue['id']} {issue['component']}",
                f"  - Assigned to: {issue['assigned_to']}",
                f"  - Description: {issue['description']}",
                ""
            ])

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _run_checked(self, args: List[str], cwd: str) -> Dict:
        """Run a command safely (no shell) and return status/output."""
        try:
            proc = subprocess.run(
                args,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=90,
                check=False
            )
            return {
                "ok": proc.returncode == 0,
                "code": proc.returncode,
                "stdout": proc.stdout[-1200:],
                "stderr": proc.stderr[-1200:]
            }
        except Exception as e:
            return {"ok": False, "code": -1, "stdout": "", "stderr": str(e)}

    def _run_execution_smoke_checks(self):
        """Behavioral checks: syntax/build/test commands for generated apps."""
        checks = [
            ("backend", "backend_engineer"),
            ("frontend", "frontend_engineer"),
            ("api", "api_designer"),
        ]

        for rel_dir, owner in checks:
            abs_dir = self._path(*rel_dir.split("/"))
            if not os.path.isdir(abs_dir):
                continue

            package_json = os.path.join(abs_dir, "package.json")
            if not os.path.exists(package_json):
                continue

            install = self._run_checked(["npm", "install", "--silent"], abs_dir)
            if not install["ok"]:
                self._report(
                    component=f"{rel_dir}/package.json",
                    description=f"npm install failed (code {install['code']}): {install['stderr']}",
                    assigned_to=owner,
                    severity="HIGH"
                )
                continue

            build = self._run_checked(["npm", "run", "--if-present", "build"], abs_dir)
            if not build["ok"]:
                self._report(
                    component=f"{rel_dir} build",
                    description=f"Build smoke check failed (code {build['code']}): {build['stderr']}",
                    assigned_to=owner,
                    severity="HIGH"
                )

            tests = self._run_checked(["npm", "run", "--if-present", "test"], abs_dir)
            if not tests["ok"]:
                self._report(
                    component=f"{rel_dir} tests",
                    description=f"Test smoke check failed (code {tests['code']}): {tests['stderr']}",
                    assigned_to=owner,
                    severity="MEDIUM"
                )

    def review_and_record(self) -> List[Dict]:
        """Run review checks and record issues to shared issues tracker."""
        before = self.issues_tracker.get_open_issues()
        before_ids = {i["id"] for i in before}

        known_roles = ["database_architect", "security_engineer", "backend_engineer", "frontend_engineer", "qa_engineer"]
        required_agents = (((self.ledger or {}).get("agent_specifications") or {}).get("required_agents") or [])
        if isinstance(required_agents, list) and required_agents:
            roles_to_check = [r for r in known_roles if r in required_agents]
            if not roles_to_check:
                roles_to_check = known_roles
        else:
            roles_to_check = known_roles

        for role in roles_to_check:
            self._check_readme_presence(role)

        self._check_frontend_backend_api_alignment()
        self._check_schema_order()
        self._check_security()
        self._check_qa_paths()
        self._check_backend_imports()
        self._check_checkout_completeness()
        self._run_execution_smoke_checks()

        after = self.issues_tracker.get_open_issues()
        new_issues = [i for i in after if i["id"] not in before_ids]
        self._write_review_report(new_issues)
        return new_issues
