"""
Lightweight local validator endpoint used by agent_orchestrator_v3.py.

It is intentionally simple and deterministic:
- Python: AST parse syntax checks
- JavaScript/TypeScript: TypeScript compiler front-end checks (tsc) when available

HTTP API
POST /validate
Body:
{
  "role": "backend_engineer",
  "workspace": "./workspace/backend_engineer",
  "files": ["app.js", "controllers/foo.ts"]
}

Response:
{
  "diagnostics": [
    {
      "tool": "local_ast|tsc",
      "severity": "error|warning",
      "file": "relative/path",
      "line": 1,
      "column": 1,
      "message": "..."
    }
  ]
}
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List


TSC_LINE_RE = re.compile(r"^(.*)\((\d+),(\d+)\):\s(error|warning)\sTS\d+:\s(.*)$")
REQUIRE_RE = re.compile(r"require\(\s*['\"](\.[^'\"]+)['\"]\s*\)")
IMPORT_FROM_RE = re.compile(r"import\s+[^;]*?\sfrom\s+['\"](\.[^'\"]+)['\"]")
IMPORT_SIDE_RE = re.compile(r"import\s+['\"](\.[^'\"]+)['\"]")


def _safe_relpath(path: str, workspace: str) -> str:
    try:
        return os.path.relpath(path, workspace).replace("\\", "/")
    except Exception:
        return path.replace("\\", "/")


def _resolve_target_files(workspace: str, files: List[str]) -> List[str]:
    if files:
        targets = []
        ws_abs = os.path.abspath(workspace)
        for rel in files:
            abs_file = os.path.abspath(os.path.join(workspace, rel))
            if abs_file.startswith(ws_abs) and os.path.isfile(abs_file):
                targets.append(abs_file)
        return targets

    collected = []
    for root, _, filenames in os.walk(workspace):
        for name in filenames:
            collected.append(os.path.join(root, name))
    return collected


def _python_diagnostics(workspace: str, files: List[str]) -> List[Dict]:
    diags: List[Dict] = []
    for abs_file in files:
        if not abs_file.endswith(".py"):
            continue
        rel = _safe_relpath(abs_file, workspace)
        try:
            with open(abs_file, "r", encoding="utf-8", errors="ignore") as f:
                ast.parse(f.read(), filename=rel)
        except SyntaxError as e:
            diags.append({
                "tool": "local_ast",
                "severity": "error",
                "file": rel,
                "line": int(e.lineno or 1),
                "column": int((e.offset or 1) - 1),
                "message": str(e.msg or "Invalid Python syntax")
            })
        except Exception as e:
            diags.append({
                "tool": "local_ast",
                "severity": "error",
                "file": rel,
                "line": 1,
                "column": 0,
                "message": f"Failed to parse Python file: {str(e)}"
            })
    return diags


def _pick_tsc_command() -> List[str]:
    if shutil.which("tsc"):
        try:
            proc = subprocess.run(["tsc", "--version"], capture_output=True, text=True, timeout=3)
            out = (proc.stdout or "") + (proc.stderr or "")
            if "Version" in out:
                return ["tsc"]
        except Exception:
            pass

    if shutil.which("npx"):
        # Use explicit package resolution to avoid resolving unrelated "tsc" binaries.
        try:
            proc = subprocess.run(["npx", "-y", "-p", "typescript", "tsc", "--version"], capture_output=True, text=True, timeout=12)
            out = (proc.stdout or "") + (proc.stderr or "")
            if "Version" in out:
                return ["npx", "-y", "-p", "typescript", "tsc"]
        except Exception:
            pass

    # Fallback to bundled TypeScript from VS Code if available.
    if shutil.which("node"):
        bundled_candidates = [
            "/usr/share/code/resources/app/extensions/node_modules/typescript/lib/tsc.js",
            "/usr/lib/code/resources/app/extensions/node_modules/typescript/lib/tsc.js",
            "/Applications/Visual Studio Code.app/Contents/Resources/app/extensions/node_modules/typescript/lib/tsc.js",
        ]
        for tsc_js in bundled_candidates:
            if os.path.exists(tsc_js):
                try:
                    proc = subprocess.run(["node", tsc_js, "--version"], capture_output=True, text=True, timeout=5)
                    out = (proc.stdout or "") + (proc.stderr or "")
                    if "Version" in out:
                        return ["node", tsc_js]
                except Exception:
                    pass

    return []


def _resolve_relative_module_exists(abs_file: str, spec: str) -> bool:
    """Resolve Node-like relative module candidates for local import existence checks."""
    base = os.path.abspath(os.path.join(os.path.dirname(abs_file), spec))
    candidates = [
        base,
        base + ".js",
        base + ".jsx",
        base + ".ts",
        base + ".tsx",
        base + ".mjs",
        base + ".cjs",
        base + ".json",
        os.path.join(base, "index.js"),
        os.path.join(base, "index.jsx"),
        os.path.join(base, "index.ts"),
        os.path.join(base, "index.tsx"),
        os.path.join(base, "index.mjs"),
        os.path.join(base, "index.cjs"),
        os.path.join(base, "index.json"),
    ]
    return any(os.path.exists(c) for c in candidates)


def _local_import_diagnostics(workspace: str, abs_file: str) -> List[Dict]:
    diags: List[Dict] = []
    rel = _safe_relpath(abs_file, workspace)

    try:
        with open(abs_file, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception:
        return diags

    for idx, line in enumerate(lines, start=1):
        specs = []
        specs.extend(m.group(1) for m in REQUIRE_RE.finditer(line))
        specs.extend(m.group(1) for m in IMPORT_FROM_RE.finditer(line))
        specs.extend(m.group(1) for m in IMPORT_SIDE_RE.finditer(line))

        for spec in specs:
            if not spec.startswith("."):
                continue
            if not _resolve_relative_module_exists(abs_file, spec):
                diags.append({
                    "tool": "local_imports",
                    "severity": "error",
                    "file": rel,
                    "line": idx,
                    "column": 1,
                    "message": f"Unresolved local import: {spec}",
                })

    return diags


def _js_ts_diagnostics(workspace: str, files: List[str]) -> List[Dict]:
    diags: List[Dict] = []
    tsc_cmd = _pick_tsc_command()

    js_like = (".js", ".mjs", ".cjs")
    ts_like = (".ts", ".tsx", ".jsx")

    # JS baseline: node --check where supported
    node_exists = shutil.which("node") is not None

    exts = js_like + ts_like
    for abs_file in files:
        if not abs_file.endswith(exts):
            continue
        rel = _safe_relpath(abs_file, workspace)

        # Catch unresolved relative imports early (for both JS and TS family files).
        diags.extend(_local_import_diagnostics(workspace, abs_file))

        if abs_file.endswith(js_like):
            if node_exists:
                try:
                    proc = subprocess.run(
                        ["node", "--check", abs_file],
                        cwd=workspace,
                        capture_output=True,
                        text=True,
                        timeout=6
                    )
                    if proc.returncode != 0:
                        msg = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
                        diags.append({
                            "tool": "node_check",
                            "severity": "error",
                            "file": rel,
                            "line": 1,
                            "column": 1,
                            "message": msg.splitlines()[0] if msg else "JavaScript syntax check failed",
                        })
                except Exception as e:
                    diags.append({
                        "tool": "node_check",
                        "severity": "error",
                        "file": rel,
                        "line": 1,
                        "column": 1,
                        "message": f"node --check failed: {str(e)}",
                    })
            else:
                diags.append({
                    "tool": "node_check",
                    "severity": "warning",
                    "file": rel,
                    "line": 1,
                    "column": 1,
                    "message": "Node.js not available. JavaScript syntax check skipped.",
                })

        if not abs_file.endswith(ts_like):
            continue

        if not tsc_cmd:
            diags.append({
                "tool": "tsc",
                "severity": "warning",
                "file": rel,
                "line": 1,
                "column": 1,
                "message": "TypeScript compiler not available. TS/TSX/JSX checks skipped.",
            })
            continue

        cmd = tsc_cmd + [
            "--pretty", "false",
            "--noEmit",
            "--allowJs", "true",
            "--checkJs", "false",
            "--jsx", "preserve",
            abs_file,
        ]

        try:
            proc = subprocess.run(
                cmd,
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=12
            )
            output = (proc.stdout or "") + "\n" + (proc.stderr or "")
            if proc.returncode == 0:
                continue

            parsed_any = False
            for line in output.splitlines():
                m = TSC_LINE_RE.match(line.strip())
                if not m:
                    continue
                parsed_any = True
                file_path, line_no, col_no, sev, msg = m.groups()
                diags.append({
                    "tool": "tsc",
                    "severity": "error" if sev.lower() == "error" else "warning",
                    "file": _safe_relpath(file_path, workspace),
                    "line": int(line_no),
                    "column": int(col_no),
                    "message": msg.strip(),
                })

            if not parsed_any:
                # If output format is unknown, still provide actionable message.
                snippet = "\n".join([l for l in output.splitlines() if l.strip()][:3])
                diags.append({
                    "tool": "tsc",
                    "severity": "error",
                    "file": rel,
                    "line": 1,
                    "column": 1,
                    "message": snippet or "TypeScript/JavaScript validation failed",
                })
        except subprocess.TimeoutExpired:
            diags.append({
                "tool": "tsc",
                "severity": "error",
                "file": rel,
                "line": 1,
                "column": 1,
                "message": "Validation timed out for this file",
            })
        except Exception as e:
            diags.append({
                "tool": "tsc",
                "severity": "error",
                "file": rel,
                "line": 1,
                "column": 1,
                "message": f"Validator execution failed: {str(e)}",
            })

    return diags


def run_validation(payload: Dict) -> Dict:
    workspace = str(payload.get("workspace", "")).strip()
    files = payload.get("files", []) or []
    if not workspace:
        return {"diagnostics": [{"tool": "validator", "severity": "error", "message": "Missing workspace"}]}

    workspace = os.path.abspath(workspace)
    if not os.path.isdir(workspace):
        return {"diagnostics": [{"tool": "validator", "severity": "error", "message": f"Workspace not found: {workspace}"}]}

    targets = _resolve_target_files(workspace, files)
    diagnostics = []
    diagnostics.extend(_python_diagnostics(workspace, targets))
    diagnostics.extend(_js_ts_diagnostics(workspace, targets))
    return {"diagnostics": diagnostics}


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/validate":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error":"not_found"}')
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8", errors="ignore"))
            response = run_validation(payload)
            body = json.dumps(response).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            body = json.dumps({"error": {"code": -32603, "message": str(e)}}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, format, *args):
        return


def main():
    host = os.getenv("LSP_VALIDATOR_HOST", "127.0.0.1")
    port = int(os.getenv("LSP_VALIDATOR_PORT", "8765"))
    server = ThreadingHTTPServer((host, port), _Handler)
    print(f"LSP validator listening on http://{host}:{port}/validate")
    server.serve_forever()


if __name__ == "__main__":
    main()
