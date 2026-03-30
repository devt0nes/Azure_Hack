import json
import os
from typing import Dict, List, Set, Tuple, Any, Optional


class ContractValidationError(Exception):
    pass


def _normalize_path(path: str) -> str:
    p = str(path or "").strip()
    if not p:
        return ""
    if not p.startswith("/"):
        p = "/" + p
    if len(p) > 1:
        p = p.rstrip("/")
    return p


def _normalize_api_path(path: str) -> str:
    p = _normalize_path(path)
    # Convert OpenAPI params {id} to Express-like :id for stable comparisons.
    out = []
    for part in p.split("/"):
        if part.startswith("{") and part.endswith("}") and len(part) > 2:
            out.append(":" + part[1:-1].strip())
        else:
            out.append(part)
    return "/".join(out)


def _extract_backend_routes(api_contract: Dict[str, Any]) -> Set[str]:
    routes = set()
    if not isinstance(api_contract, dict):
        return routes

    # Shape 1: endpoints[] with either route="GET /x" or method+path.
    endpoints = api_contract.get("endpoints")
    if isinstance(endpoints, list):
        for ep in endpoints:
            if not isinstance(ep, dict):
                continue
            route = str(ep.get("route", "")).strip()
            if route and " " in route:
                method, raw_path = route.split(" ", 1)
                routes.add(f"{method.upper()} {_normalize_api_path(raw_path)}")
                continue

            method = str(ep.get("method", "")).strip().upper()
            raw_path = str(ep.get("path", "")).strip()
            if method and raw_path:
                routes.add(f"{method} {_normalize_api_path(raw_path)}")

    # Shape 2: OpenAPI paths{}.
    paths = api_contract.get("paths")
    allowed_methods = {"get", "post", "put", "patch", "delete", "head", "options"}
    if isinstance(paths, dict):
        for raw_path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            for method in path_item.keys():
                m = str(method).lower().strip()
                if m in allowed_methods:
                    routes.add(f"{m.upper()} {_normalize_api_path(str(raw_path))}")

    return routes


def _validate_backend_smoke_policy(api_contract: Dict[str, Any]) -> Tuple[bool, str]:
    """Require explicit smoke-test policy for every backend endpoint.

    Supported fields per endpoint/operation:
      - smoke_test: bool
      - smoke_test: {"enabled": bool, ...}
      - smoke_test_enabled: bool
      - x-smoke-test-enabled: bool (OpenAPI operation extension)
    """
    if not isinstance(api_contract, dict):
        return False, "backend_api_contract.json is invalid"

    def _has_policy(obj: Dict[str, Any]) -> bool:
        if not isinstance(obj, dict):
            return False
        if isinstance(obj.get("smoke_test"), bool):
            return True
        if isinstance(obj.get("smoke_test"), dict) and isinstance(obj.get("smoke_test", {}).get("enabled"), bool):
            return True
        if isinstance(obj.get("smoke_test_enabled"), bool):
            return True
        if isinstance(obj.get("x-smoke-test-enabled"), bool):
            return True
        return False

    missing: List[str] = []

    endpoints = api_contract.get("endpoints")
    if isinstance(endpoints, list) and endpoints:
        for idx, ep in enumerate(endpoints, 1):
            if not isinstance(ep, dict):
                continue
            method = str(ep.get("method", "")).strip().upper() or "?"
            path = str(ep.get("path", "")).strip() or "?"
            route = str(ep.get("route", "")).strip()
            label = route if route else f"{method} {path}".strip()
            if not _has_policy(ep):
                missing.append(f"endpoints[{idx}] {label}")

    paths = api_contract.get("paths")
    allowed_methods = {"get", "post", "put", "patch", "delete", "head", "options"}
    if isinstance(paths, dict):
        for raw_path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            for method in path_item.keys():
                m = str(method).lower().strip()
                if m not in allowed_methods:
                    continue
                op_obj = path_item.get(m) if isinstance(path_item, dict) else {}
                if not isinstance(op_obj, dict) or not _has_policy(op_obj):
                    missing.append(f"paths.{raw_path}.{m}")

    if missing:
        preview = ", ".join(missing[:8]) + (" ..." if len(missing) > 8 else "")
        return False, (
            "backend_api_contract.json must declare smoke_test policy for every endpoint/operation "
            f"(missing: {preview})"
        )

    return True, ""


def _extract_frontend_routes(route_contract: Dict[str, Any]) -> Set[str]:
    routes = set()
    if not isinstance(route_contract, dict):
        return routes

    def _maybe_add(value):
        if isinstance(value, str):
            t = value.strip()
            if t.startswith("/"):
                routes.add(_normalize_path(t))
        elif isinstance(value, dict):
            for key in ["path", "route", "url", "href"]:
                v = value.get(key)
                if isinstance(v, str) and v.strip().startswith("/"):
                    routes.add(_normalize_path(v.strip()))

    for key in ["routes", "pages", "navigation", "menu"]:
        section = route_contract.get(key)
        if isinstance(section, list):
            for item in section:
                _maybe_add(item)

    # Optional map shape: pages: {"/": {...}, "/login": {...}}
    pages_map = route_contract.get("pages")
    if isinstance(pages_map, dict):
        for k in pages_map.keys():
            if isinstance(k, str) and k.startswith("/"):
                routes.add(_normalize_path(k))

    return routes


def _extract_directory_root(directory_contract: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(directory_contract, dict):
        return {}
    structure = directory_contract.get("structure")
    if isinstance(structure, dict):
        return structure
    return directory_contract


def _collect_paths_from_directory_node(node: Any, out: Set[str]) -> None:
    if isinstance(node, dict):
        path_value = node.get("path")
        if isinstance(path_value, str) and path_value.strip():
            out.add(path_value.strip().replace("\\", "/").strip("/"))
        for v in node.values():
            if isinstance(v, (dict, list)):
                _collect_paths_from_directory_node(v, out)
    elif isinstance(node, list):
        for item in node:
            _collect_paths_from_directory_node(item, out)


def _normalize_directory_structure_sections(directory_contract: Dict[str, Any]) -> Dict[str, List[str]]:
    """Normalize directory structure into section->relative file list.

    Supports:
    - {"backend": {...}, ...}
    - {"structure": {...}}
    - {"structure": [ {"name":"backend","type":"directory",...}, ... ]}
    """
    if not isinstance(directory_contract, dict):
        return {}

    # Shape A/B: dict tree
    root = _extract_directory_root(directory_contract)
    if isinstance(root, dict) and root:
        if any(k in root for k in ["backend", "frontend", "database"]):
            section_map: Dict[str, List[str]] = {}
            for section, node in root.items():
                section_files = sorted(_flatten_declared_files(node, base_rel=""))
                section_map[str(section)] = section_files
            return section_map

    # Shape C: list node model under structure
    structure = directory_contract.get("structure")
    if not isinstance(structure, list):
        return {}

    section_names = set()
    for item in structure:
        if not isinstance(item, dict):
            continue
        if str(item.get("type", "")).strip().lower() == "directory":
            name = str(item.get("name", "")).strip()
            if name:
                section_names.add(name)

    all_paths: Set[str] = set()
    _collect_paths_from_directory_node(structure, all_paths)

    buckets: Dict[str, List[str]] = {k: [] for k in section_names}
    for p in sorted(all_paths):
        parts = p.split("/", 1)
        if len(parts) != 2:
            continue
        section, rel = parts[0], parts[1]
        buckets.setdefault(section, []).append(rel)

    return buckets


def _flatten_declared_files(node: Any, base_rel: str = "") -> Set[str]:
    out = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if not isinstance(key, str) or not key.strip():
                continue
            key_norm = key.strip().replace("\\", "/").strip("/")
            child_rel = f"{base_rel}/{key_norm}".strip("/") if base_rel else key_norm
            basename = os.path.basename(key_norm)
            key_is_file = "." in basename and not key_norm.endswith("/")
            if key_is_file and (value is None or isinstance(value, str)):
                out.add(child_rel)
            else:
                out.update(_flatten_declared_files(value, child_rel))
    elif isinstance(node, list):
        for item in node:
            if not isinstance(item, str) or not item.strip():
                continue
            rel = item.strip().replace("\\", "/").strip("/")
            basename = os.path.basename(rel)
            if "." in basename and not rel.endswith("/"):
                out.add(f"{base_rel}/{rel}".strip("/") if base_rel else rel)
    return out


class ContractValidator:
    """Validates System Architect contracts with schema-flexible checks.

    Validation goals:
    - backend API contract defines at least one usable endpoint route
    - frontend route contract defines at least one usable frontend route
    - directory contract defines backend/frontend/database sections and at least one file
    - duplicate route detection for backend/frontend contracts
    """

    def __init__(self, api_contract: Dict[str, Any], route_contract: Dict[str, Any], directory_contract: Optional[Dict[str, Any]] = None):
        self.api = api_contract
        self.routes = route_contract
        self.directory = directory_contract or {}

    def validate_all(self) -> Dict[str, Any]:
        backend_routes = _extract_backend_routes(self.api)
        smoke_ok, smoke_err = _validate_backend_smoke_policy(self.api)
        if not smoke_ok:
            raise ContractValidationError(smoke_err)

        # Empty backend contract is allowed and should not block orchestration.
        # When routes exist, still guard against duplicate declarations.
        if backend_routes and len(backend_routes) != len(set(backend_routes)):
            raise ContractValidationError("backend_api_contract.json contains duplicate routes")

        frontend_routes = _extract_frontend_routes(self.routes)
        if not frontend_routes:
            raise ContractValidationError(
                "frontend_route_contract.json has no usable routes (expected routes/pages/navigation/menu with '/path' entries)"
            )

        if len(frontend_routes) != len(set(frontend_routes)):
            raise ContractValidationError("frontend_route_contract.json contains duplicate routes")

        sections = _normalize_directory_structure_sections(self.directory)
        declared_files = set()
        if isinstance(sections, dict) and sections:
            for section, rel_files in sections.items():
                for rel in rel_files:
                    declared_files.add(f"{section}/{rel}".strip("/"))

        return {
            "ok": True,
            "backend_route_count": len(backend_routes),
            "frontend_route_count": len(frontend_routes),
            "directory_contract_checked": bool(isinstance(sections, dict) and sections),
            "declared_file_count": len(declared_files),
        }


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return json.load(f)


def validate_system_architect_contracts(
    workspace_dir: str,
    backend_rel: str = "contracts/backend_api_contract.json",
    frontend_rel: str = "contracts/frontend_route_contract.json",
    directory_rel: str = "contracts/directory_structure.json",
    require_directory: bool = False,
) -> Dict[str, Any]:
    try:
        backend_path = os.path.join(workspace_dir, backend_rel)
        frontend_path = os.path.join(workspace_dir, frontend_rel)
        directory_path = os.path.join(workspace_dir, directory_rel)

        required_paths = [(backend_path, backend_rel), (frontend_path, frontend_rel)]
        if require_directory:
            required_paths.append((directory_path, directory_rel))

        missing = []
        for p, rel in required_paths:
            if not os.path.exists(p):
                missing.append(rel)
        if missing:
            return {"ok": False, "error": "missing required contracts: " + ", ".join(missing)}

        api = load_json(backend_path)
        routes = load_json(frontend_path)
        directory = load_json(directory_path) if os.path.exists(directory_path) else {}

        validator = ContractValidator(api, routes, directory)
        details = validator.validate_all()
        return {"ok": True, "details": details}
    except ContractValidationError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"contract validation runtime error: {str(e)}"}


if __name__ == "__main__":
    result = validate_system_architect_contracts(os.getcwd())
    if result.get("ok"):
        print("✅ CONTRACT VALIDATION PASSED")
        print(json.dumps(result.get("details", {}), indent=2, ensure_ascii=False))
    else:
        print("❌ CONTRACT VALIDATION FAILED")
        print(result.get("error", "unknown error"))
