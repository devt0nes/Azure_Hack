import argparse
import json
import os
import select
import socket
import subprocess
import sys
import tempfile
import time
import shutil
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlparse

import requests


def _smoke_log(role: str, message: str):
    print(f"[SMOKE][{role}] {message}", flush=True)


def _read_json(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}


def _parse_env_file(path: Path) -> dict:
    values = {}
    if not path.exists():
        return values
    try:
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = str(raw or "").strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            key = str(k or "").strip()
            if not key:
                continue
            val = str(v or "").strip().strip('"').strip("'")
            values[key] = val
    except Exception:
        return {}
    return values


def _build_startup_env(role_workspace: Path, role: str, env_updates: dict = None) -> dict:
    merged = dict(env_updates or {})

    # Local role env files should be honored by smoke runs.
    file_vars = {}
    for name in [".env", ".env.local", ".env.example"]:
        file_vars.update(_parse_env_file(role_workspace / name))

    if role == "backend_engineer":
        # Preserve current process env first, then role file vars, then fallback defaults.
        if "MONGODB_URI" not in merged:
            merged["MONGODB_URI"] = (
                os.getenv("MONGODB_URI")
                or os.getenv("MONGO_URI")
                or file_vars.get("MONGODB_URI")
                or file_vars.get("MONGO_URI")
                or "mongodb://127.0.0.1:27017/exotic-library"
            )

        if "JWT_SECRET" not in merged:
            merged["JWT_SECRET"] = (
                os.getenv("JWT_SECRET")
                or file_vars.get("JWT_SECRET")
                or "smoke-jwt-secret"
            )

    return merged


def _wait_for_port(host: str, port: int, timeout: int = 30):
    deadline = time.time() + max(1, timeout)
    hosts = []
    primary = str(host or "").strip()
    if primary:
        hosts.append(primary)
    for candidate in ["127.0.0.1", "localhost", "::1"]:
        if candidate not in hosts:
            hosts.append(candidate)

    while time.time() < deadline:
        for h in hosts:
            with suppress(Exception):
                with socket.create_connection((h, port), timeout=1.5):
                    return True
        time.sleep(0.5)
    return False


def _is_port_open(host: str, port: int) -> bool:
    hosts = []
    primary = str(host or "").strip()
    if primary:
        hosts.append(primary)
    for candidate in ["127.0.0.1", "localhost", "::1"]:
        if candidate not in hosts:
            hosts.append(candidate)

    for h in hosts:
        with suppress(Exception):
            with socket.create_connection((h, port), timeout=0.8):
                return True
    return False


def _find_free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        s.listen(1)
        return int(s.getsockname()[1])


def _replace_url_port(url: str, fallback_host: str, new_port: int) -> str:
    parsed = urlparse(str(url or ""))
    scheme = parsed.scheme or "http"
    host = parsed.hostname or fallback_host
    return f"{scheme}://{host}:{int(new_port)}"


def _extract_backend_endpoints(contract: dict):
    out = []
    endpoints = contract.get("endpoints")
    if isinstance(endpoints, list):
        for ep in endpoints:
            if not isinstance(ep, dict):
                continue
            method = str(ep.get("method", "GET")).upper().strip()
            path = str(ep.get("path", "")).strip()
            if path.startswith("/"):
                responses = ep.get("responses") if isinstance(ep, dict) else {}
                expected_statuses = []
                if isinstance(responses, dict):
                    for code in responses.keys():
                        try:
                            expected_statuses.append(int(str(code).strip()))
                        except Exception:
                            continue
                out.append(
                    {
                        "method": method,
                        "path": path,
                        "request_example": _extract_request_example(ep),
                        "dependency_profile": _infer_endpoint_dependency_profile(ep),
                        "id": ep.get("id") or "",
                        "expected_statuses": sorted(set(expected_statuses)),
                        "smoke_test_enabled": _resolve_smoke_test_enabled(ep),
                        "smoke_test_present": _has_smoke_test_field(ep),
                    }
                )
    paths = contract.get("paths")
    if isinstance(paths, dict):
        for p, item in paths.items():
            if not isinstance(item, dict):
                continue
            for m in item.keys():
                method = str(m).upper().strip()
                if method in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
                    op_obj = item.get(str(m).lower()) if isinstance(item, dict) else {}
                    responses = op_obj.get("responses") if isinstance(op_obj, dict) else {}
                    expected_statuses = []
                    if isinstance(responses, dict):
                        for code in responses.keys():
                            try:
                                expected_statuses.append(int(str(code).strip()))
                            except Exception:
                                continue
                    out.append(
                        {
                            "method": method,
                            "path": str(p).strip(),
                            "request_example": _extract_openapi_request_example(op_obj),
                            "dependency_profile": _infer_endpoint_dependency_profile(op_obj or {}),
                            "id": "",
                            "expected_statuses": sorted(set(expected_statuses)),
                            "smoke_test_enabled": _resolve_smoke_test_enabled(op_obj or {}),
                            "smoke_test_present": _has_smoke_test_field(op_obj or {}),
                        }
                    )
    seen = set()
    dedup = []
    for ep in out:
        method = ep.get("method", "GET")
        path = ep.get("path", "")
        key = f"{method} {path}"
        if key in seen:
            continue
        seen.add(key)
        dedup.append(ep)
    return dedup


def _extract_openapi_request_example(op_obj: dict):
    if not isinstance(op_obj, dict):
        return {}
    request_body = op_obj.get("requestBody")
    if not isinstance(request_body, dict):
        return {}
    content = request_body.get("content")
    if not isinstance(content, dict):
        return {}
    app_json = content.get("application/json")
    if not isinstance(app_json, dict):
        return {}
    if isinstance(app_json.get("example"), dict):
        return app_json.get("example")
    examples = app_json.get("examples")
    if isinstance(examples, dict):
        for _, val in examples.items():
            if isinstance(val, dict) and isinstance(val.get("value"), dict):
                return val.get("value")
    return {}


def _extract_request_example(endpoint: dict):
    if not isinstance(endpoint, dict):
        return {}
    keys = [
        "example",
        "request_example",
        "requestExample",
        "example_request",
        "exampleRequest",
        "sample_request",
        "sampleRequest",
        "smoke_test_request",
        "smokeTestRequest",
    ]
    for k in keys:
        val = endpoint.get(k)
        if isinstance(val, dict):
            return val
        if isinstance(val, str):
            txt = val.strip()
            if txt.startswith("{") and txt.endswith("}"):
                with suppress(Exception):
                    parsed = json.loads(txt)
                    if isinstance(parsed, dict):
                        return parsed
    examples = endpoint.get("examples")
    if isinstance(examples, dict):
        req = examples.get("request")
        if isinstance(req, dict):
            return req
    return {}


def _has_smoke_test_field(endpoint: dict) -> bool:
    if not isinstance(endpoint, dict):
        return False
    return (
        "smoke_test" in endpoint
        or "smoke_test_enabled" in endpoint
        or "x-smoke-test-enabled" in endpoint
    )


def _resolve_smoke_test_enabled(endpoint: dict):
    """Resolve explicit per-endpoint smoke policy.

    Accepted endpoint fields:
    - smoke_test: bool
    - smoke_test: { "enabled": bool, ... }
    - smoke_test_enabled: bool
    - x-smoke-test-enabled: bool (OpenAPI extension)

    Returns:
      True / False when explicitly declared, else None.
    """
    if not isinstance(endpoint, dict):
        return None

    raw = endpoint.get("smoke_test")
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("enabled"), bool):
        return raw.get("enabled")

    raw_enabled = endpoint.get("smoke_test_enabled")
    if isinstance(raw_enabled, bool):
        return raw_enabled

    ext_enabled = endpoint.get("x-smoke-test-enabled")
    if isinstance(ext_enabled, bool):
        return ext_enabled

    return None


def _infer_endpoint_dependency_profile(endpoint: dict):
    profile = {
        "requires_db": False,
        "requires_external_service": False,
        "requires_api_key": False,
    }
    if not isinstance(endpoint, dict):
        return profile

    text_chunks = [
        str(endpoint.get("id", "")),
        str(endpoint.get("name", "")),
        str(endpoint.get("description", "")),
        str(endpoint.get("notes", "")),
    ]

    dep_fields = [
        endpoint.get("dependencies"),
        endpoint.get("external_dependencies"),
        endpoint.get("requires"),
        endpoint.get("depends_on"),
    ]
    for val in dep_fields:
        if isinstance(val, list):
            text_chunks.extend(str(v) for v in val)
        elif isinstance(val, str):
            text_chunks.append(val)

    flattened = " ".join(text_chunks).lower()

    if endpoint.get("requires_database") is True or endpoint.get("requires_db") is True:
        profile["requires_db"] = True
    if endpoint.get("requires_api_key") is True:
        profile["requires_api_key"] = True
    if endpoint.get("requires_external_service") is True:
        profile["requires_external_service"] = True

    db_tokens = ["db", "database", "postgres", "mysql", "mongo", "redis", "cosmos", "sqlite"]
    ext_tokens = ["stripe", "openai", "azure", "s3", "blob", "storage", "service bus", "mail", "smtp"]
    key_tokens = ["api key", "apikey", "secret", "token", "credential"]

    if any(tok in flattened for tok in db_tokens):
        profile["requires_db"] = True
    if any(tok in flattened for tok in ext_tokens):
        profile["requires_external_service"] = True
    if any(tok in flattened for tok in key_tokens):
        profile["requires_api_key"] = True

    return profile


def _is_dependency_related_failure(status_code: int, body_text: str, dep_profile: dict):
    if not isinstance(dep_profile, dict):
        dep_profile = {}
    if status_code in {401, 403}:
        return True
    if status_code < 500:
        return False

    text = (body_text or "").lower()
    dep_markers = [
        "database",
        "db",
        "connection",
        "timeout",
        "api key",
        "apikey",
        "credential",
        "secret",
        "service unavailable",
        "external",
        "openai",
        "stripe",
        "storage",
        "cosmos",
        "postgres",
    ]
    if any(m in text for m in dep_markers):
        return True

    return bool(
        dep_profile.get("requires_db")
        or dep_profile.get("requires_external_service")
        or dep_profile.get("requires_api_key")
    )


def _extract_frontend_routes(contract: dict):
    out = []
    routes = contract.get("routes")
    if isinstance(routes, list):
        for r in routes:
            if isinstance(r, str) and r.startswith("/"):
                out.append(r)
            elif isinstance(r, dict):
                path = r.get("path") or r.get("route") or r.get("url")
                if isinstance(path, str) and path.startswith("/"):
                    out.append(path)
    pages = contract.get("pages")
    if isinstance(pages, dict):
        for k in pages.keys():
            if isinstance(k, str) and k.startswith("/"):
                out.append(k)
    seen = set()
    dedup = []
    for route in out:
        if route in seen:
            continue
        seen.add(route)
        dedup.append(route)
    return dedup


def _materialize_path(path: str) -> str:
    s = path
    s = s.replace("{", "").replace("}", "")
    parts = []
    for part in s.split("/"):
        if not part:
            parts.append(part)
            continue
        if part.startswith(":"):
            parts.append("1")
        elif part in {"id", "bookId", "userId", "projectId"}:
            parts.append("1")
        else:
            parts.append(part)
    return "/".join(parts)


def _start_process(command, cwd: Path, extra_env: dict = None):
    env = os.environ.copy()
    if isinstance(extra_env, dict):
        for k, v in extra_env.items():
            if v is None:
                continue
            env[str(k)] = str(v)
    return subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )


def _tail_output(proc: subprocess.Popen, max_chars: int = 2000):
    if not proc or not proc.stdout:
        return ""
    chunks = []
    with suppress(Exception):
        fd = proc.stdout.fileno()
        while True:
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                break
            data = os.read(fd, 4096)
            if not data:
                break
            chunks.append(data.decode("utf-8", errors="ignore"))
    text = "".join(chunks)
    return text[-max_chars:]


def _remaining_seconds(deadline_ts: float) -> float:
    return max(0.0, float(deadline_ts) - time.time())


def _stop_process(proc: subprocess.Popen):
    if not proc:
        return
    with suppress(Exception):
        proc.terminate()
        proc.wait(timeout=4)
    if proc.poll() is None:
        with suppress(Exception):
            proc.kill()


def _pick_start_command(role_workspace: Path, role: str, scripts: dict, desired_port: int):
    env_updates = {"PORT": str(desired_port)}
    if role == "backend_engineer":
        if "dev" in scripts:
            return ["npm", "run", "dev"], "npm run dev", env_updates
        if "start" in scripts:
            return ["npm", "run", "start"], "npm run start", env_updates
        if (role_workspace / "server.js").exists():
            return ["node", "server.js"], "node server.js", env_updates
        if (role_workspace / "app.js").exists():
            return ["node", "app.js"], "node app.js", env_updates
    else:
        env_updates["VITE_PORT"] = str(desired_port)
        env_updates["HOST"] = "127.0.0.1"
        if "dev" in scripts:
            # Vite accepts --port and --strictPort forwarded via npm '--'.
            return ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", str(desired_port), "--strictPort"], "npm run dev", env_updates
        if "start" in scripts:
            return ["npm", "run", "start", "--", "--host", "127.0.0.1", "--port", str(desired_port), "--strictPort"], "npm run start", env_updates
    return None, "", {}


def _is_npm_package_present(role_workspace: Path, package_name: str) -> bool:
    pkg = str(package_name or "").strip()
    if not pkg:
        return True
    return (role_workspace / "node_modules" / pkg / "package.json").exists()


def _ensure_node_dependencies(role_workspace: Path, package_json: dict, role: str):
    if not isinstance(package_json, dict):
        return {"ok": True, "installed": False, "missing": []}

    deps = package_json.get("dependencies", {})
    dev_deps = package_json.get("devDependencies", {})
    missing = []

    if isinstance(deps, dict):
        for name in deps.keys():
            if not _is_npm_package_present(role_workspace, str(name)):
                missing.append(str(name))
    if isinstance(dev_deps, dict):
        for name in dev_deps.keys():
            if not _is_npm_package_present(role_workspace, str(name)):
                missing.append(str(name))

    missing = sorted(set(missing))
    if not missing:
        return {"ok": True, "installed": False, "missing": []}

    preview = ", ".join(missing[:8]) + ("..." if len(missing) > 8 else "")
    _smoke_log(role, f"installing missing npm dependencies: {preview}")
    try:
        completed = subprocess.run(
            ["npm", "install", "--no-audit", "--no-fund"],
            cwd=str(role_workspace),
            capture_output=True,
            text=True,
            timeout=180,
        )
        out = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
        if completed.returncode != 0:
            return {
                "ok": False,
                "installed": True,
                "missing": missing,
                "error": f"npm install failed with exit code {completed.returncode}",
                "output": out[-2500:],
            }
        return {
            "ok": True,
            "installed": True,
            "missing": missing,
            "output": out[-1200:],
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "installed": True,
            "missing": missing,
            "error": "npm install timed out",
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "installed": False,
            "missing": missing,
            "error": "npm executable not found",
        }
    except Exception as exc:
        return {
            "ok": False,
            "installed": False,
            "missing": missing,
            "error": f"npm install failed: {exc}",
        }


def _check_backend_endpoints(base_url: str, backend_contract: dict, deadline_ts: float):
    errors = []
    warnings = []
    checks = []
    endpoints = _extract_backend_endpoints(backend_contract)
    if not endpoints:
        return ["No backend endpoints found in backend_api_contract.json"], [], checks

    for ep in endpoints:
        if _remaining_seconds(deadline_ts) <= 0:
            errors.append("Smoke time budget exceeded while checking backend endpoints")
            break
        method = ep.get("method", "GET")
        raw_path = ep.get("path", "")
        dep_profile = ep.get("dependency_profile") if isinstance(ep, dict) else {}
        request_example = ep.get("request_example") if isinstance(ep, dict) else {}
        expected_statuses = ep.get("expected_statuses") if isinstance(ep, dict) else []
        smoke_test_enabled = ep.get("smoke_test_enabled") if isinstance(ep, dict) else None
        smoke_test_present = bool(ep.get("smoke_test_present")) if isinstance(ep, dict) else False
        if not isinstance(expected_statuses, list):
            expected_statuses = []
        expected_statuses = [int(s) for s in expected_statuses if isinstance(s, int) or str(s).isdigit()]
        # Treat 5xx as hard failures regardless of contract docs.
        expected_non_5xx_statuses = [s for s in expected_statuses if int(s) < 500]
        path = _materialize_path(raw_path)
        url = f"{base_url.rstrip('/')}{path}"

        if not smoke_test_present:
            errors.append(
                f"Endpoint missing required smoke policy field (smoke_test/smoke_test_enabled): {method} {path}"
            )
            checks.append({"kind": "endpoint", "target": f"{method} {path}", "status": "policy_missing"})
            continue

        if smoke_test_enabled is False:
            checks.append({"kind": "endpoint", "target": f"{method} {path}", "status": "skipped_by_policy"})
            _smoke_log("backend_engineer", f"skip {method} {path} (smoke policy disabled)")
            continue

        _smoke_log("backend_engineer", f"probe {method} {path}")
        try:
            payload = request_example if isinstance(request_example, dict) else {}
            req_timeout = max(1.0, min(8.0, _remaining_seconds(deadline_ts)))
            if method == "GET":
                resp = requests.get(url, timeout=req_timeout)
            elif method == "POST":
                resp = requests.post(url, json=payload, timeout=req_timeout)
            elif method == "PUT":
                resp = requests.put(url, json=payload, timeout=req_timeout)
            elif method == "PATCH":
                resp = requests.patch(url, json=payload, timeout=req_timeout)
            elif method == "DELETE":
                resp = requests.delete(url, json=payload if payload else None, timeout=req_timeout)
            else:
                resp = requests.request(method, url, timeout=req_timeout)

            checks.append({"kind": "endpoint", "target": f"{method} {path}", "status": resp.status_code})
            _smoke_log("backend_engineer", f"result {method} {path} -> HTTP {resp.status_code}")
            if expected_non_5xx_statuses and int(resp.status_code) in expected_non_5xx_statuses:
                continue
            if resp.status_code in {401, 403}:
                warnings.append(
                    f"Auth-gated endpoint returned {resp.status_code} (treated as warning in unauthenticated smoke): {method} {path}"
                )
                continue
            if resp.status_code >= 500:
                body_text = ""
                with suppress(Exception):
                    body_text = resp.text[:800]
                if _is_dependency_related_failure(resp.status_code, body_text, dep_profile):
                    warnings.append(
                        f"Dependency-related failure tolerated for endpoint {method} {path}: HTTP {resp.status_code}"
                    )
                else:
                    errors.append(f"Endpoint returned server error {resp.status_code}: {method} {path}")
            elif expected_non_5xx_statuses:
                allowed = ", ".join(str(x) for x in sorted(set(expected_non_5xx_statuses)))
                errors.append(
                    f"Endpoint returned unexpected status {resp.status_code}: {method} {path} (allowed: {allowed})"
                )
            elif resp.status_code == 404:
                errors.append(f"Endpoint returned 404: {method} {path}")
        except Exception as exc:
            _smoke_log("backend_engineer", f"result {method} {path} -> EXCEPTION {exc}")
            if dep_profile.get("requires_db") or dep_profile.get("requires_external_service") or dep_profile.get("requires_api_key"):
                warnings.append(f"Dependency-related request failure tolerated: {method} {path} -> {exc}")
            else:
                errors.append(f"Endpoint request failed: {method} {path} -> {exc}")

    return errors, warnings, checks


def _check_frontend_routes(base_url: str, route_contract: dict, deadline_ts: float):
    errors = []
    checks = []
    routes = _extract_frontend_routes(route_contract)
    if not routes:
        return ["No frontend routes found in frontend_route_contract.json"], checks

    for route in routes:
        if _remaining_seconds(deadline_ts) <= 0:
            errors.append("Smoke time budget exceeded while checking frontend routes")
            break
        url = f"{base_url.rstrip('/')}{route}"
        _smoke_log("frontend_engineer", f"probe GET {route}")
        try:
            req_timeout = max(1.0, min(8.0, _remaining_seconds(deadline_ts)))
            resp = requests.get(url, timeout=req_timeout)
            checks.append({"kind": "route", "target": route, "status": resp.status_code})
            _smoke_log("frontend_engineer", f"result GET {route} -> HTTP {resp.status_code}")
            if resp.status_code >= 500:
                errors.append(f"Route returned server error {resp.status_code}: {route}")
            elif resp.status_code == 404:
                errors.append(f"Route returned 404: {route}")
        except Exception as exc:
            _smoke_log("frontend_engineer", f"result GET {route} -> EXCEPTION {exc}")
            errors.append(f"Route request failed: {route} -> {exc}")

    return errors, checks


def _capture_frontend_browser_console(role_workspace: Path, base_url: str, routes: list, timeout_seconds: int = 30, deadline_ts: float = 0.0):
        """Capture browser console/page errors for frontend routes via headless browser.

        Tries Playwright first, then Puppeteer. If neither is available, returns skipped+warning.
        """
        node_bin = shutil.which("node")
        if not node_bin:
                return {
                        "ok": False,
                        "skipped": False,
                        "checks": [{"kind": "browser_console", "status": "node_missing"}],
                        "warnings": [],
                        "errors": ["browser console capture requires Node.js, but node executable was not found"],
                }

        browser_dep = _ensure_browser_automation_dependency(role_workspace)
        if not browser_dep.get("ok"):
            return {
                "ok": False,
                "skipped": False,
                "checks": [{"kind": "browser_console", "status": "dependency_bootstrap_failed"}],
                "warnings": [],
                "errors": [str(browser_dep.get("error") or "browser automation dependency bootstrap failed")],
            }

        remaining = _remaining_seconds(deadline_ts) if deadline_ts else float(timeout_seconds)
        if remaining <= 0:
            return {
                "ok": False,
                "skipped": False,
                "checks": [{"kind": "browser_console", "status": "timeout_budget_exhausted"}],
                "warnings": [],
                "errors": ["browser console capture skipped: smoke time budget exhausted"],
            }
        timeout_ms = max(4000, int(min(float(timeout_seconds), remaining) * 1000))
        script = r"""
const routes = JSON.parse(process.argv[2] || '[]');
const baseUrl = process.argv[3] || 'http://127.0.0.1:5180';
const timeoutMs = parseInt(process.argv[4] || '10000', 10);

let launcher = null;
let libName = '';
let closeBrowser = async (_b) => {};

async function pickBrowser() {
    try {
        const pw = await import('playwright');
        libName = 'playwright';
        launcher = async () => pw.chromium.launch({ headless: true });
        closeBrowser = async (b) => { if (b) await b.close(); };
        return;
    } catch (_) {}

    try {
        const pptr = await import('puppeteer');
        libName = 'puppeteer';
        launcher = async () => pptr.default.launch({ headless: true, args: ['--no-sandbox'] });
        closeBrowser = async (b) => { if (b) await b.close(); };
        return;
    } catch (_) {}
}

function fullUrl(route) {
    const r = String(route || '/');
    return `${baseUrl.replace(/\/$/, '')}${r.startsWith('/') ? r : `/${r}`}`;
}

async function run() {
    await pickBrowser();
    if (!launcher) {
        console.log(JSON.stringify({
            ok: false,
            skipped: false,
            checks: [{ kind: 'browser_console', status: 'library_unavailable', reason: 'playwright/puppeteer not available' }],
            warnings: [],
            errors: ['playwright/puppeteer not available after dependency bootstrap']
        }));
        return;
    }

    const browser = await launcher();
    const errors = [];
    const warnings = [];
    const checks = [];

    try {
        for (const route of routes) {
            const page = await browser.newPage();
            const routeErrors = [];
            const routeWarnings = [];

            // Filter function: Skip network/fetch errors that are expected when external resources are unavailable
            function isExternalResourceError(text) {
                const networkPatterns = [
                    /net::ERR_CONNECTION_REFUSED/i,
                    /ERR_CONNECTION_REFUSED/i,
                    /Failed to fetch/i,
                    /fetch.*failed/i,
                    /networkidle.*timeout/i,
                    /timeout.*network/i,
                    /ERR_NAME_NOT_RESOLVED/i,
                    /ERR_NETWORK_UNREACHABLE/i,
                    /ECONNREFUSED/i,
                    /ENOTFOUND/i,
                    /connect ECONNREFUSED/i,
                ];
                return networkPatterns.some(pattern => pattern.test(text));
            }

            page.on('console', (msg) => {
                const type = String(msg.type() || '').toLowerCase();
                const text = String(msg.text() || '').trim();
                if (!text) return;
                // Skip external resource/network errors (fetch failures, connection refused, etc.)
                if (isExternalResourceError(text)) {
                    return;
                }
                if (type === 'error') routeErrors.push(text);
                else if (type === 'warning' || type === 'warn') routeWarnings.push(text);
            });

            page.on('pageerror', (err) => {
                const text = String((err && err.message) || err || 'unknown page error');
                // Skip external resource/network errors
                if (isExternalResourceError(text)) {
                    return;
                }
                routeErrors.push(text);
            });

            const url = fullUrl(route);
            try {
                await page.goto(url, { waitUntil: 'networkidle', timeout: timeoutMs });
                await page.waitForTimeout(400);
                checks.push({ kind: 'browser_console', target: route, status: 'loaded', library: libName });
            } catch (e) {
                const navErr = `Navigation failed for ${route}: ${String((e && e.message) || e)}`;
                routeErrors.push(navErr);
                checks.push({ kind: 'browser_console', target: route, status: 'navigation_failed', library: libName });
            }

            for (const e of routeErrors) errors.push(`Browser console/page error on ${route}: ${e}`);
            for (const w of routeWarnings) warnings.push(`Browser console warning on ${route}: ${w}`);

            await page.close();
        }

        console.log(JSON.stringify({
            ok: errors.length === 0,
            skipped: false,
            checks,
            warnings,
            errors
        }));
    } finally {
        await closeBrowser(browser);
    }
}

run().catch((e) => {
    console.log(JSON.stringify({
        ok: false,
        skipped: false,
        checks: [{ kind: 'browser_console', status: 'runner_failed' }],
        warnings: [],
        errors: [`browser console capture runner failed: ${String((e && e.message) || e)}`]
    }));
});
"""

        script_path = None
        try:
                with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False, encoding="utf-8", dir=str(role_workspace)) as tf:
                        tf.write(script)
                        script_path = tf.name

                completed = subprocess.run(
                        [node_bin, script_path, json.dumps(routes or []), base_url, str(timeout_ms)],
                        cwd=str(role_workspace),
                        capture_output=True,
                        text=True,
                        timeout=max(10, int(min(300, max(5, remaining + 5)))),
                )
                output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
                parsed = None
                for line in reversed(output.splitlines()):
                        line = line.strip()
                        if not line:
                                continue
                        with suppress(Exception):
                                parsed = json.loads(line)
                                break

                if not isinstance(parsed, dict):
                        return {
                                "ok": False,
                                "skipped": False,
                                "checks": [{"kind": "browser_console", "status": "parse_failed"}],
                                "warnings": [],
                                "errors": ["browser console capture did not return parseable JSON"],
                        }

                parsed.setdefault("checks", [])
                parsed.setdefault("warnings", [])
                parsed.setdefault("errors", [])

                if completed.returncode != 0 and parsed.get("ok"):
                        parsed["ok"] = False
                        parsed["errors"].append(f"browser console capture process exited with code {completed.returncode}")

                return parsed
        except subprocess.TimeoutExpired:
                return {
                        "ok": False,
                        "skipped": False,
                        "checks": [{"kind": "browser_console", "status": "timeout"}],
                        "warnings": [],
                        "errors": ["browser console capture timed out"],
                }
        except Exception as exc:
                return {
                        "ok": False,
                        "skipped": False,
                        "checks": [{"kind": "browser_console", "status": "runner_exception"}],
                        "warnings": [],
                        "errors": [f"browser console capture failed: {exc}"],
                }
        finally:
                if script_path:
                        with suppress(Exception):
                                os.unlink(script_path)


def _ensure_browser_automation_dependency(role_workspace: Path) -> dict:
        """Ensure either playwright or puppeteer is installed for browser console checks."""

        node_modules = role_workspace / "node_modules"
        if (node_modules / "puppeteer" / "package.json").exists():
            return {"ok": True, "provider": "puppeteer"}

        has_playwright = (node_modules / "playwright" / "package.json").exists()
        if has_playwright:
            try:
                completed = subprocess.run(
                    ["npx", "playwright", "install", "chromium"],
                    cwd=str(role_workspace),
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if completed.returncode == 0:
                    return {"ok": True, "provider": "playwright"}
            except Exception:
                # Fall back to puppeteer bootstrap below.
                pass

        install_attempts = [
            ["npm", "install", "--no-audit", "--no-fund", "--save-dev", "puppeteer"],
            ["npm", "install", "--no-audit", "--no-fund", "--save-dev", "playwright"],
            ["npm", "install", "--no-audit", "--no-fund", "--no-save", "puppeteer"],
            ["npm", "install", "--no-audit", "--no-fund", "--no-save", "playwright"],
        ]

        failures = []

        for cmd in install_attempts:
            try:
                completed = subprocess.run(
                    cmd,
                    cwd=str(role_workspace),
                    capture_output=True,
                    text=True,
                    timeout=240,
                )
                if completed.returncode != 0:
                    out = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
                    failures.append(f"{' '.join(cmd)} -> exit {completed.returncode}: {out[-400:]}")
                    continue

                if (node_modules / "playwright" / "package.json").exists():
                    return {"ok": True, "provider": "playwright"}
                if (node_modules / "puppeteer" / "package.json").exists():
                    return {"ok": True, "provider": "puppeteer"}
            except Exception:
                failures.append(f"{' '.join(cmd)} -> exception")
                continue

        return {
            "ok": False,
            "error": (
                "Unable to install playwright/puppeteer for frontend browser-console validation. "
                + (" Install attempts: " + " | ".join(failures[:3]) if failures else "")
            ),
        }


def run_smoke(
    workspace_dir: Path,
    role: str,
    backend_url: str,
    frontend_url: str,
    backend_port: int,
    frontend_port: int,
    timeout_seconds: int,
    max_total_seconds: int = 300,
):
    errors = []
    warnings = []
    checks = []
    deadline_ts = time.time() + max(30, int(max_total_seconds or 300))

    backend_contract = _read_json(workspace_dir / "contracts" / "backend_api_contract.json")
    frontend_contract = _read_json(workspace_dir / "contracts" / "frontend_route_contract.json")

    role_workspace = workspace_dir / ("backend" if role == "backend_engineer" else "frontend")
    package_json = _read_json(role_workspace / "package.json")
    scripts = package_json.get("scripts", {}) if isinstance(package_json, dict) else {}
    if not isinstance(scripts, dict):
        scripts = {}

    dep_bootstrap = _ensure_node_dependencies(role_workspace, package_json, role)
    checks.append(
        {
            "kind": "dependency_bootstrap",
            "target": "npm install",
            "status": (
                "ok"
                if dep_bootstrap.get("ok") and dep_bootstrap.get("installed")
                else ("already_satisfied" if dep_bootstrap.get("ok") else "failed")
            ),
            "missing_count": len(dep_bootstrap.get("missing") or []),
        }
    )
    if dep_bootstrap.get("ok") and not dep_bootstrap.get("installed"):
        _smoke_log(role, "npm dependencies already satisfied; npm install skipped")
    if not dep_bootstrap.get("ok"):
        err = dep_bootstrap.get("error") or "dependency bootstrap failed"
        errors.append(err)
        return {
            "ok": False,
            "errors": errors,
            "checks": checks,
            "output": dep_bootstrap.get("output", ""),
        }

    desired_port = backend_port if role == "backend_engineer" else frontend_port
    host = "127.0.0.1"
    probe_port = desired_port
    if _is_port_open(host, desired_port):
        probe_port = _find_free_port(host)
        msg = (
            f"standard port {desired_port} already in use; "
            f"using temporary smoke port {probe_port} for this run"
        )
        warnings.append(msg)
        _smoke_log(role, msg)

    command, label, env_updates = _pick_start_command(role_workspace, role, scripts, desired_port=probe_port)
    if not command:
        return {
            "ok": False,
            "errors": [
                f"No startup command detected for {role}. Expected npm script (dev/start) or node app.js/server.js"
            ],
            "checks": checks,
        }

    proc = None
    try:
        _smoke_log(role, f"startup command: {label}")
        startup_env = _build_startup_env(role_workspace, role, env_updates)
        startup_env_keys = ["PORT", "MONGODB_URI", "JWT_SECRET", "VITE_PORT", "HOST"]
        startup_env_log = ", ".join(
            [f"{k}={'set' if startup_env.get(k) else 'unset'}" for k in startup_env_keys if k in startup_env]
        )
        _smoke_log(role, f"startup env overrides: {startup_env_log or 'none'}")
        proc = _start_process(command, role_workspace, extra_env=startup_env)
        checks.append({"kind": "startup", "target": label, "status": "started"})

        _smoke_log(role, f"waiting for port {probe_port} on {host}")
        wait_timeout = max(1, min(int(timeout_seconds), int(_remaining_seconds(deadline_ts))))
        if wait_timeout <= 0 or not _wait_for_port(host, probe_port, timeout=wait_timeout):
            errors.append(f"Service did not open expected port {probe_port} for {role} using '{label}'")
            return {"ok": False, "errors": errors, "checks": checks, "output": _tail_output(proc)}
        _smoke_log(role, f"port {probe_port} is open")

        backend_base = _replace_url_port(backend_url, host, probe_port if role == "backend_engineer" else backend_port)
        frontend_base = _replace_url_port(frontend_url, host, probe_port if role == "frontend_engineer" else frontend_port)

        if role == "backend_engineer":
            endpoint_errors, endpoint_warnings, endpoint_checks = _check_backend_endpoints(
                backend_base,
                backend_contract,
                deadline_ts=deadline_ts,
            )
            errors.extend(endpoint_errors)
            warnings.extend(endpoint_warnings)
            checks.extend(endpoint_checks)
        else:
            route_errors, route_checks = _check_frontend_routes(
                frontend_base,
                frontend_contract,
                deadline_ts=deadline_ts,
            )
            errors.extend(route_errors)
            checks.extend(route_checks)

            browser = _capture_frontend_browser_console(
                role_workspace=role_workspace,
                base_url=frontend_base,
                routes=_extract_frontend_routes(frontend_contract),
                timeout_seconds=timeout_seconds,
                deadline_ts=deadline_ts,
            )
            checks.extend(browser.get("checks", []) or [])
            warnings.extend(browser.get("warnings", []) or [])
            browser_errors = browser.get("errors", []) or []
            if browser.get("skipped"):
                _smoke_log(role, "browser console capture skipped")
            else:
                _smoke_log(role, f"browser console capture checks: {len(browser.get('checks', []) or [])}")
            for w in (browser.get("warnings", []) or [])[:10]:
                _smoke_log(role, f"console warning: {w}")
            for e in browser_errors[:15]:
                _smoke_log(role, f"console error: {e}")
            errors.extend(browser_errors)

        return {
            "ok": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "checks": checks,
            "output": _tail_output(proc),
        }
    finally:
        _stop_process(proc)


def main():
    parser = argparse.ArgumentParser(description="Contract-aware runtime smoke test")
    parser.add_argument("--workspace", required=True, help="Absolute workspace path")
    parser.add_argument("--role", required=True, choices=["backend_engineer", "frontend_engineer"])
    parser.add_argument("--backend-url", default=os.getenv("SMOKE_BACKEND_URL", "http://127.0.0.1:5100"))
    parser.add_argument("--frontend-url", default=os.getenv("SMOKE_FRONTEND_URL", "http://127.0.0.1:5180"))
    parser.add_argument("--backend-port", type=int, default=int(os.getenv("SMOKE_BACKEND_PORT", "5100")))
    parser.add_argument("--frontend-port", type=int, default=int(os.getenv("SMOKE_FRONTEND_PORT", "5180")))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("SMOKE_STARTUP_TIMEOUT_SECONDS", "30")))
    parser.add_argument("--max-total-seconds", type=int, default=int(os.getenv("SMOKE_MAX_TOTAL_SECONDS", "300")))
    args = parser.parse_args()

    result = run_smoke(
        workspace_dir=Path(args.workspace),
        role=args.role,
        backend_url=args.backend_url,
        frontend_url=args.frontend_url,
        backend_port=args.backend_port,
        frontend_port=args.frontend_port,
        timeout_seconds=args.timeout,
        max_total_seconds=args.max_total_seconds,
    )
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
