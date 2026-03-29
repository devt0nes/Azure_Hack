"""
tooly.py - Universal Tool Suite for AI Agents

This module provides a collection of tools that can be used by any AI agent
for code generation, development, and testing tasks. Tools handle:
- File operations (read, write, list)
- Command execution
- Code search
- Syntax validation and linting
"""

import os
import json
import subprocess
import re
import shlex
from pathlib import Path
import sys

from azure_runtime_sync import (
    download_blob_to_local_path,
    sync_blob_prefix_to_local_dir,
    sync_local_dir_to_blob_prefix,
    upload_local_path_to_blob,
    write_text_azure_first,
)


def _detect_repo_root() -> Path:
    env_root = (os.getenv("NEXUS_ROOT_DIR") or "").strip()
    if env_root:
        return Path(env_root).resolve()

    here = Path(__file__).resolve()
    if here.parent.name == "platform-backend" and here.parent.parent.name.startswith("Azure_Hack-"):
        return here.parent.parent.parent

    return here.parent


REPO_ROOT = _detect_repo_root()
DEFAULT_WORKSPACE_DIR = str((REPO_ROOT / "workspace").resolve())
KNOWN_WORKSPACE_ROOT_DIRS = {
    "backend",
    "frontend",
    "database",
    "contracts",
    "tests",
    "infra",
    "docs",
    "api",
    "config",
}


class ToolConfig:
    """Configuration for tool execution"""
    def __init__(self, allowed_root=DEFAULT_WORKSPACE_DIR, timeout=60):
        self.allowed_root = str(Path(allowed_root).resolve())
        self.timeout = timeout
        self.workspace_root = str(self._infer_workspace_root())
        os.environ.setdefault("NEXUS_WORKSPACE_ROOT", self.workspace_root)
        os.makedirs(self.allowed_root, exist_ok=True)

    def _infer_workspace_root(self) -> Path:
        root = Path(self.allowed_root).resolve()
        if any((root / d).exists() for d in KNOWN_WORKSPACE_ROOT_DIRS):
            return root

        parent = root.parent
        if parent and parent.exists() and any((parent / d).exists() for d in KNOWN_WORKSPACE_ROOT_DIRS):
            return parent

        return root
    
    def resolve_path(self, path):
        """
        Maps agent paths (/workspace/...) to local paths (./workspace/...)
        Ensures all file operations stay within allowed root.
        """
        raw = str(path or "").strip()
        allowed_root = Path(self.allowed_root).resolve()
        workspace_root = Path(self.workspace_root).resolve()

        if raw in {"", ".", "./"}:
            return str(allowed_root)

        if raw.startswith("/workspace"):
            relative_path = raw[len("/workspace"):].lstrip("/")
            candidate = workspace_root / relative_path
            return str(candidate.resolve())

        if os.path.isabs(raw):
            candidate = Path(raw)
            return str(candidate.resolve())

        normalized = raw.lstrip("./")
        candidate = allowed_root / normalized

        first_segment = normalized.split("/", 1)[0] if normalized else ""
        if (not candidate.exists()) and first_segment in KNOWN_WORKSPACE_ROOT_DIRS:
            candidate = workspace_root / normalized

        if (not candidate.exists()) and first_segment == allowed_root.name:
            candidate = workspace_root / normalized

        return str(candidate.resolve())
    
    def is_safe_path(self, full_path):
        """Verify path is within allowed root"""
        try:
            Path(full_path).resolve().relative_to(Path(self.allowed_root).resolve())
            return True
        except Exception:
            return False


class FilesTools:
    """File operation tools"""
    
    def __init__(self, config):
        self.config = config
    
    def read_file(self, file_path, start_line=None, end_line=None):
        """Read the contents of a file from the workspace.

        Optional line slicing:
        - start_line: 1-based inclusive start line
        - end_line: 1-based inclusive end line
        """
        try:
            full_path = self.config.resolve_path(file_path)
            if not self.config.is_safe_path(full_path):
                return "ERROR: Access Denied. You may only access files in the workspace directory."

            # Azure-first hydration for runtime files.
            ok, detail = download_blob_to_local_path(full_path)
            if ok:
                print(f"[AzureBlob][tooly][read_file] hydrated: {detail}", file=sys.stderr, flush=True)

            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            if start_line is None and end_line is None:
                return content

            lines = content.splitlines()
            total = len(lines)
            if total == 0:
                return ""

            s = 1 if start_line is None else int(start_line)
            e = total if end_line is None else int(end_line)

            if s < 1:
                s = 1
            if e < s:
                return ""
            if s > total:
                return ""
            if e > total:
                e = total

            return "\n".join(lines[s - 1:e])
        except FileNotFoundError:
            return f"ERROR: File not found: {file_path}"
        except Exception as e:
            return f"ERROR: Failed to read file: {str(e)}"
    
    def write_file(self, file_path, content):
        """Write content to a file in the workspace"""
        try:
            full_path = self.config.resolve_path(file_path)
            if not self.config.is_safe_path(full_path):
                return "ERROR: Access Denied. You may only access files in the workspace directory."

            ok, detail = write_text_azure_first(full_path, str(content or ""))
            if ok:
                print(f"[AzureBlob][tooly][write_file] azure-first write: {detail}", file=sys.stderr, flush=True)
            else:
                print(f"[AzureBlob][tooly][write_file] azure-first failed: {detail}", file=sys.stderr, flush=True)
                return f"ERROR: Failed to write file (azure-first): {detail}"
            return f"Successfully wrote to {full_path}"
        except Exception as e:
            return f"ERROR: Failed to write file: {str(e)}"
    
    def list_files(self, directory):
        """List all files in a directory"""
        try:
            requested = str(directory or ".")
            full_path = self.config.resolve_path(requested)
            if not self.config.is_safe_path(full_path):
                return "ERROR: Access Denied."
            
            if not os.path.isdir(full_path):
                # Try hydrating directory from Azure runtime prefix before failing.
                ok, detail = sync_blob_prefix_to_local_dir(full_path)
                if ok:
                    print(f"[AzureBlob][tooly][list_files] hydrated: {detail}", file=sys.stderr, flush=True)

            if not os.path.isdir(full_path):
                root_name = Path(self.config.allowed_root).name
                guidance = (
                    f"Try '.' to list the current root ({self.config.allowed_root}), "
                    f"or '/workspace/<dir>' from workspace root ({self.config.workspace_root})."
                )
                if requested.strip("/") == root_name:
                    guidance = (
                        f"You are already rooted at '{root_name}'. Try '.' or a subdirectory like 'pages', 'components', or 'routes'."
                    )
                return f"ERROR: Directory not found: {directory} (resolved: {full_path}). {guidance}"
            
            files = os.listdir(full_path)
            return json.dumps(files)
        except Exception as e:
            return f"ERROR: Failed to list directory: {str(e)}"


class CommandTools:
    """Command execution tools"""
    
    def __init__(self, config):
        self.config = config
        # Commands that are not allowed for security
        self.forbidden_keywords = ["rm", "curl", "sudo", "dd", ":/"]
    
    def run_command(self, command, cwd=None):
        """Execute shell command in the workspace directory"""
        # Security check
        cmd = str(command or "")
        # Block dangerous commands by token, not substring (e.g., avoid matching 'backend' for 'dd').
        token_block = re.compile(r"(^|[\s;&|()])(?:rm|curl|sudo|dd)(?=$|[\s;&|()])", re.IGNORECASE)
        if token_block.search(cmd) or ":/" in cmd:
            return "ERROR: Access Denied. The requested command contains forbidden keywords!"
        
        try:
            working_dir = cwd or os.path.abspath(self.config.allowed_root)
            
            if not self.config.is_safe_path(working_dir):
                return "ERROR: Unsafe working directory"

            ok_in, detail_in = sync_blob_prefix_to_local_dir(working_dir)
            if ok_in:
                print(f"[AzureBlob][tooly][run_command] hydrated: {detail_in}", file=sys.stderr, flush=True)
            
            cmd_parts = shlex.split(cmd)
            if not cmd_parts:
                return "ERROR: Empty command"

            result = subprocess.run(
                cmd_parts,
                shell=False,
                capture_output=True,
                text=True,
                timeout=self.config.timeout,
                cwd=working_dir
            )
            
            status = "SUCCESS" if result.returncode == 0 else "FAILED"

            ok_out, detail_out = sync_local_dir_to_blob_prefix(working_dir)
            if ok_out:
                print(f"[AzureBlob][tooly][run_command] uploaded: {detail_out}", file=sys.stderr, flush=True)

            return f"STATUS: {status}\nEXIT_CODE: {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        except subprocess.TimeoutExpired:
            return f"ERROR: Command timed out after {self.config.timeout} seconds."
        except Exception as e:
            return f"ERROR: {str(e)}"


class SearchTools:
    """Code and file search tools"""
    
    def __init__(self, config):
        self.config = config
    
    def search_files(self, pattern, directory=".", file_type="*"):
        """
        Search for files matching a pattern.
        Args:
            pattern: Glob pattern (e.g., "*.js", "*.py")
            directory: Root directory to search from
            file_type: Not used with glob, kept for API compatibility
        """
        try:
            full_path = self.config.resolve_path(directory)
            if not self.config.is_safe_path(full_path):
                return "ERROR: Access Denied."

            ok, detail = sync_blob_prefix_to_local_dir(full_path)
            if ok:
                print(f"[AzureBlob][tooly][search_files] hydrated: {detail}", file=sys.stderr, flush=True)
            
            import glob
            search_pattern = os.path.join(full_path, "**", pattern)
            matches = glob.glob(search_pattern, recursive=True)
            
            # Return relative paths from workspace
            relative_matches = [
                os.path.relpath(m, os.path.abspath(self.config.allowed_root))
                for m in matches
            ]
            
            return json.dumps(relative_matches[:100])  # Limit to 100 results
        except Exception as e:
            return f"ERROR: Failed to search files: {str(e)}"
    
    def search_in_files(self, query, directory=".", file_pattern="*"):
        """
        Search for text/regex in files.
        Args:
            query: Text or regex pattern to search for
            directory: Root directory to search from
            file_pattern: Glob pattern for files to search
        """
        try:
            full_path = self.config.resolve_path(directory)
            if not self.config.is_safe_path(full_path):
                return "ERROR: Access Denied."

            ok, detail = sync_blob_prefix_to_local_dir(full_path)
            if ok:
                print(f"[AzureBlob][tooly][search_in_files] hydrated: {detail}", file=sys.stderr, flush=True)
            
            import glob
            
            results = []
            search_pattern = os.path.join(full_path, "**", file_pattern)
            files = glob.glob(search_pattern, recursive=True)
            
            for file_path in files[:50]:  # Limit files to search
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        for line_no, line in enumerate(f, 1):
                            if re.search(query, line, re.IGNORECASE):
                                rel_path = os.path.relpath(file_path, os.path.abspath(self.config.allowed_root))
                                results.append({
                                    "file": rel_path,
                                    "line": line_no,
                                    "content": line.strip()
                                })
                except:
                    pass
            
            return json.dumps(results[:50])  # Limit results
        except Exception as e:
            return f"ERROR: Failed to search in files: {str(e)}"


class ValidationTools:
    """Code validation and linting tools"""
    
    def __init__(self, config):
        self.config = config

    def _resolve_case_insensitive(self, full_path):
        candidate = Path(full_path)
        if candidate.exists():
            return str(candidate.resolve())

        parent = candidate.parent
        if not parent.exists() or not parent.is_dir():
            return None

        target_name = candidate.name.lower()
        try:
            for child in parent.iterdir():
                if child.name.lower() == target_name:
                    return str(child.resolve())
        except Exception:
            return None
        return None
    
    def check_syntax(self, file_path, language=None):
        """
        Check syntax of a file without executing it.
        Detects language automatically or uses provided language.
        """
        try:
            full_path = self.config.resolve_path(file_path)
            if not self.config.is_safe_path(full_path):
                return "ERROR: Access Denied."

            ok, detail = download_blob_to_local_path(full_path)
            if ok:
                print(f"[AzureBlob][tooly][check_syntax] hydrated: {detail}", file=sys.stderr, flush=True)

            ci_path = self._resolve_case_insensitive(full_path)
            if ci_path and self.config.is_safe_path(ci_path):
                full_path = ci_path
            
            if not os.path.exists(full_path):
                return f"ERROR: File not found: {file_path}"
            
            # Auto-detect language from extension
            if language is None:
                _, ext = os.path.splitext(file_path)
                ext = ext.lower()
                language_map = {
                    '.py': 'python',
                    '.js': 'javascript',
                    '.jsx': 'jsx',
                    '.ts': 'typescript',
                    '.tsx': 'tsx',
                    '.java': 'java',
                    '.go': 'go',
                    '.rb': 'ruby',
                    '.php': 'php',
                }
                language = language_map.get(ext, 'unknown')
            
            with open(full_path, 'r') as f:
                content = f.read()
            
            # Python syntax check
            if language in ['python', 'py']:
                try:
                    compile(content, file_path, 'exec')
                    return "✅ SYNTAX OK: No syntax errors found"
                except SyntaxError as e:
                    return f"❌ SYNTAX ERROR:\n  File: {file_path}\n  Line {e.lineno}: {e.msg}\n  {e.text}"
            
            # JavaScript/TypeScript syntax check (basic)
            elif language in ['javascript', 'typescript', 'js', 'ts', 'jsx', 'tsx']:
                return self._check_js_syntax(content, file_path, language=language)
            
            # JSON syntax check
            elif language == 'json':
                try:
                    json.loads(content)
                    return "✅ SYNTAX OK: Valid JSON"
                except json.JSONDecodeError as e:
                    return f"❌ JSON ERROR: {e.msg} at line {e.lineno}, column {e.colno}"
            
            else:
                return f"⚠️ Language '{language}' syntax checking not yet implemented"
        
        except Exception as e:
            return f"ERROR: {str(e)}"
    
    def _check_js_syntax(self, content, file_path, language=None):
        """Basic JavaScript syntax validation"""
        errors = []
        _, ext = os.path.splitext(file_path)
        ext = ext.lower()
        is_jsx_like = ext in {'.jsx', '.tsx'} or str(language or '').lower() in {'jsx', 'tsx'}
        
        # Check for common syntax issues
        if content.count('{') != content.count('}'):
            errors.append("Mismatched curly braces")
        if content.count('[') != content.count(']'):
            errors.append("Mismatched square brackets")
        if content.count('(') != content.count(')'):
            errors.append("Mismatched parentheses")
        
        # Try to use Node.js if available (skip for JSX/TSX: node -c cannot parse these directly).
        if not is_jsx_like:
            try:
                result = subprocess.run(
                    f"node -c {file_path}",
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode != 0:
                    return f"❌ SYNTAX ERROR:\n{result.stderr}"
            except:
                pass
        
        if errors:
            return f"❌ POTENTIAL SYNTAX ERRORS:\n  " + "\n  ".join(errors)

        if is_jsx_like:
            return "✅ SYNTAX OK: JSX/TSX heuristic check passed (node -c skipped for this extension)"
        
        return "✅ SYNTAX OK: No obvious syntax errors found"
    
    def lint_file(self, file_path, linter=None):
        """
        Run linting on a file.
        Automatically detects appropriate linter or uses specified one.
        """
        try:
            full_path = self.config.resolve_path(file_path)
            if not self.config.is_safe_path(full_path):
                return "ERROR: Access Denied."

            ci_path = self._resolve_case_insensitive(full_path)
            if ci_path and self.config.is_safe_path(ci_path):
                full_path = ci_path
            
            if not os.path.exists(full_path):
                root_name = Path(self.config.allowed_root).name
                guidance = (
                    f"Try a path relative to current root ({self.config.allowed_root}) "
                    f"or use '/workspace/<path>' rooted at ({self.config.workspace_root})."
                )
                if str(file_path or "").strip("/").startswith(root_name + "/"):
                    guidance = (
                        f"Path appears to include duplicated root '{root_name}'. "
                        f"Try dropping that prefix (example: 'pages/index.jsx' instead of '{root_name}/pages/index.jsx')."
                    )
                return f"ERROR: File not found: {file_path} (resolved: {full_path}). {guidance}"
            
            _, ext = os.path.splitext(file_path)
            ext = ext.lower()
            
            # Python linting
            if ext == '.py':
                return self._lint_python(full_path, file_path)
            
            # JavaScript linting
            elif ext in ['.js', '.ts', '.jsx', '.tsx']:
                return self._lint_javascript(full_path, file_path)
            
            else:
                return f"⚠️ Linting not available for {ext} files"
        
        except Exception as e:
            return f"ERROR: {str(e)}"
    
    def _lint_python(self, full_path, file_path):
        """Lint Python file using pylint or flake8"""
        try:
            # Try pylint first
            result = subprocess.run(
                f"pylint {full_path}",
                shell=True,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return "✅ LINTING OK: No issues found"
            return f"Pylint output:\n{result.stdout}{result.stderr}"
        except:
            pass
        
        try:
            # Try flake8
            result = subprocess.run(
                f"flake8 {full_path}",
                shell=True,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return "✅ LINTING OK: No issues found"
            return f"Flake8 output:\n{result.stdout}"
        except:
            return "⚠️ No Python linter (pylint/flake8) found in environment"
    
    def _lint_javascript(self, full_path, file_path):
        """Lint JavaScript file using eslint"""
        try:
            result = subprocess.run(
                f"eslint {full_path}",
                shell=True,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return "✅ LINTING OK: No issues found"
            return f"ESLint output:\n{result.stdout}{result.stderr}"
        except:
            return "⚠️ ESLint not found in environment"


class TemplateTools:
    """Starter-template tools backed by Cosmos DB."""

    def __init__(self, config):
        self.config = config

    def _resolve_target_dir(self, target_directory: str) -> Path:
        workspace_root = Path(self.config.workspace_root).resolve()
        target_raw = str(target_directory or "").strip().replace("\\", "/")
        if not target_raw:
            target_raw = "."

        if target_raw.startswith("/workspace/"):
            target_raw = target_raw[len("/workspace/"):]
        elif target_raw == "/workspace":
            target_raw = "."

        target_abs = (workspace_root / target_raw).resolve()
        if not str(target_abs).startswith(str(workspace_root)):
            raise ValueError(f"Target directory is outside workspace: {target_directory}")
        return target_abs

    def _write_template_files(self, target_abs: Path, files_map: dict, overwrite: bool = False) -> dict:
        created = 0
        updated = 0
        skipped = 0
        errors = []

        workspace_root = Path(self.config.workspace_root).resolve()

        for rel_path, content in (files_map or {}).items():
            try:
                rel = str(rel_path or "").strip().replace("\\", "/").lstrip("/")
                if not rel:
                    continue
                abs_file = (target_abs / rel).resolve()
                if not str(abs_file).startswith(str(workspace_root)):
                    errors.append(f"Skipped unsafe file path: {rel}")
                    continue

                os.makedirs(abs_file.parent, exist_ok=True)
                if abs_file.exists() and not overwrite:
                    skipped += 1
                    continue

                with open(abs_file, "w", encoding="utf-8") as f:
                    f.write(str(content or ""))

                if abs_file.exists() and overwrite:
                    updated += 1
                else:
                    created += 1
            except Exception as e:
                errors.append(f"{rel_path}: {str(e)}")

        return {
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
        }

    def init_starter_template(self, template_id: str, target_directory: str, overwrite: bool = False):
        """Initialize a specific starter template into a target directory."""
        try:
            from cosmos_client import get_starter_template

            target_abs = self._resolve_target_dir(target_directory)
            doc = get_starter_template(template_id)
            if not isinstance(doc, dict):
                return f"ERROR: Starter template not found in Cosmos DB: {template_id}"

            files_map = doc.get("files") if isinstance(doc.get("files"), dict) else {}
            if not files_map:
                return f"ERROR: Starter template has no files payload: {template_id}"

            write_result = self._write_template_files(target_abs, files_map, overwrite=bool(overwrite))
            status = "ok" if not write_result.get("errors") else "partial"
            return json.dumps({
                "status": status,
                "template_id": doc.get("template_id") or doc.get("id"),
                "target_directory": str(target_abs),
                **write_result,
            })
        except Exception as e:
            return f"ERROR: Failed to initialize starter template: {str(e)}"

    def init_starter_template_for_stack(self, stack: list, target_directory: str, overwrite: bool = False):
        """Resolve starter template from stack tokens, then initialize it."""
        try:
            from cosmos_client import resolve_starter_template_for_stack

            tokens = []
            if isinstance(stack, list):
                tokens = [str(s).strip().lower() for s in stack if str(s).strip()]
            elif isinstance(stack, str):
                tokens = [s.strip().lower() for s in stack.split(",") if s.strip()]

            if not tokens:
                return "ERROR: stack must be a non-empty list or comma-separated string"

            doc = resolve_starter_template_for_stack(tokens)
            if not isinstance(doc, dict):
                return f"ERROR: No starter template matched stack tokens: {tokens}"

            template_id = str(doc.get("template_id") or doc.get("id") or "").strip()
            if not template_id:
                return "ERROR: Matched starter template is missing template_id"

            return self.init_starter_template(template_id, target_directory, overwrite=overwrite)
        except Exception as e:
            return f"ERROR: Failed to resolve starter template by stack: {str(e)}"


class ToolRegistry:
    """Registry of all available tools"""
    
    def __init__(self, config=None):
        if config is None:
            config = ToolConfig()
        
        self.config = config
        self.files = FilesTools(config)
        self.commands = CommandTools(config)
        self.search = SearchTools(config)
        self.validation = ValidationTools(config)
        self.templates = TemplateTools(config)
    
    def get_tool_definitions(self):
        """Return OpenAI-compatible tool definitions"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read the contents of a file from the workspace (optionally by line range)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {
                                "type": "string",
                                "description": "Path to the file, e.g. /workspace/api.js"
                            },
                            "start_line": {
                                "type": "integer",
                                "description": "Optional 1-based inclusive start line"
                            },
                            "end_line": {
                                "type": "integer",
                                "description": "Optional 1-based inclusive end line"
                            }
                        },
                        "required": ["file_path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "Write content to a file in the workspace",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {
                                "type": "string",
                                "description": "Path where to write the file"
                            },
                            "content": {
                                "type": "string",
                                "description": "The complete file content to write"
                            }
                        },
                        "required": ["file_path", "content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "list_files",
                    "description": "List files in a directory. Prefer '.' for current role root, or '/workspace/<dir>' for workspace-root paths.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "directory": {
                                "type": "string",
                                "description": "Directory to list. Examples: '.', 'pages', '/workspace/frontend'"
                            }
                        },
                        "required": ["directory"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "run_command",
                    "description": "Execute a shell command (npm install, pytest, etc)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "The command to run"
                            },
                            "cwd": {
                                "type": "string",
                                "description": "Optional working directory (must stay within allowed workspace root)"
                            }
                        },
                        "required": ["command"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_files",
                    "description": "Search for files matching a pattern (glob)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {
                                "type": "string",
                                "description": "Glob pattern (e.g., '*.js', '*.py', '**/*.test.js')"
                            },
                            "directory": {
                                "type": "string",
                                "description": "Root directory to search from (default: '.')"
                            }
                        },
                        "required": ["pattern"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_in_files",
                    "description": "Search for text/regex pattern in files",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Text or regex pattern to search for"
                            },
                            "directory": {
                                "type": "string",
                                "description": "Root directory to search from (default: '.')"
                            },
                            "file_pattern": {
                                "type": "string",
                                "description": "Glob pattern for files to search (default: '*')"
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "check_syntax",
                    "description": "Check syntax of a file without executing it",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {
                                "type": "string",
                                "description": "Path to the file to check"
                            },
                            "language": {
                                "type": "string",
                                "description": "Programming language (auto-detected if omitted)"
                            }
                        },
                        "required": ["file_path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "lint_file",
                    "description": "Lint one file. Use path relative to current role root (e.g., 'pages/index.jsx') or '/workspace/<path>'.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {
                                "type": "string",
                                "description": "File path to lint. Examples: 'pages/index.jsx', '/workspace/frontend/pages/index.jsx'"
                            }
                        },
                        "required": ["file_path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "init_starter_template",
                    "description": "Initialize a starter template from Cosmos DB into a target directory.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "template_id": {
                                "type": "string",
                                "description": "Template ID in Cosmos starter_templates container"
                            },
                            "target_directory": {
                                "type": "string",
                                "description": "Target directory under workspace (e.g., '/workspace/frontend' or 'frontend')"
                            },
                            "overwrite": {
                                "type": "boolean",
                                "description": "Overwrite existing files if true"
                            }
                        },
                        "required": ["template_id", "target_directory"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "init_starter_template_for_stack",
                    "description": "Resolve and initialize a starter template based on stack tokens (e.g. ['react','vite','tailwind','typescript']).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "stack": {
                                "description": "Stack tokens list or comma-separated string",
                                "anyOf": [
                                    {
                                        "type": "array",
                                        "items": {"type": "string"}
                                    },
                                    {
                                        "type": "string"
                                    }
                                ]
                            },
                            "target_directory": {
                                "type": "string",
                                "description": "Target directory under workspace (e.g., '/workspace/frontend' or 'frontend')"
                            },
                            "overwrite": {
                                "type": "boolean",
                                "description": "Overwrite existing files if true"
                            }
                        },
                        "required": ["stack", "target_directory"]
                    }
                }
            }
        ]
    
    def execute_tool(self, function_name, function_args):
        """Execute a tool by name with given arguments"""
        try:
            if function_name == "read_file":
                return self.files.read_file(
                    function_args.get("file_path", ""),
                    function_args.get("start_line"),
                    function_args.get("end_line"),
                )
            
            elif function_name == "write_file":
                return self.files.write_file(
                    function_args.get("file_path", ""),
                    function_args.get("content", "")
                )
            
            elif function_name == "list_files":
                return self.files.list_files(function_args.get("directory", ""))
            
            elif function_name == "run_command":
                return self.commands.run_command(
                    function_args.get("command", ""),
                    function_args.get("cwd")
                )
            
            elif function_name == "search_files":
                return self.search.search_files(
                    function_args.get("pattern", ""),
                    function_args.get("directory", ".")
                )
            
            elif function_name == "search_in_files":
                return self.search.search_in_files(
                    function_args.get("query", ""),
                    function_args.get("directory", "."),
                    function_args.get("file_pattern", "*")
                )
            
            elif function_name == "check_syntax":
                return self.validation.check_syntax(
                    function_args.get("file_path", ""),
                    function_args.get("language")
                )
            
            elif function_name == "lint_file":
                return self.validation.lint_file(function_args.get("file_path", ""))

            elif function_name == "init_starter_template":
                return self.templates.init_starter_template(
                    function_args.get("template_id", ""),
                    function_args.get("target_directory", ""),
                    bool(function_args.get("overwrite", False)),
                )

            elif function_name == "init_starter_template_for_stack":
                return self.templates.init_starter_template_for_stack(
                    function_args.get("stack", []),
                    function_args.get("target_directory", ""),
                    bool(function_args.get("overwrite", False)),
                )
            
            else:
                return f"ERROR: Unknown tool: {function_name}"
        
        except json.JSONDecodeError:
            return "ERROR: Invalid JSON arguments"
        except Exception as e:
            return f"ERROR: Tool execution failed: {str(e)}"


# Helper functions for command execution
def has_command_failed(command_result):
    """Check if a command execution failed based on exit code"""
    if "ERROR:" in command_result and "Access Denied" not in command_result:
        return True
    if "EXIT_CODE: 0" in command_result:
        return False
    if "EXIT_CODE:" in command_result:
        for line in command_result.split('\n'):
            if line.startswith("EXIT_CODE:"):
                code = line.replace("EXIT_CODE:", "").strip()
                try:
                    return int(code) != 0
                except:
                    return False
    return False


def is_done(content):
    """Check if agent has completed its task"""
    if not content:
        return False
    
    if "[DONE]" in content:
        return True
    
    try:
        data = json.loads(content)
        required_keys = ["files_created", "endpoints", "dependencies", "tests_passed"]
        return all(key in data for key in required_keys)
    except:
        return False
