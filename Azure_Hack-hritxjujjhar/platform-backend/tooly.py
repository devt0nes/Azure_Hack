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


class ToolConfig:
    """Configuration for tool execution"""
    def __init__(self, allowed_root="./workspace", timeout=60):
        self.allowed_root = allowed_root
        self.timeout = timeout
        os.makedirs(self.allowed_root, exist_ok=True)
    
    def resolve_path(self, path):
        """
        Maps agent paths (/workspace/...) to local paths (./workspace/...)
        Ensures all file operations stay within allowed root.
        """
        path = str(path or "")
        if path.startswith("/workspace"):
            relative_path = path[len("/workspace"):].lstrip("/")
            candidate = Path(self.allowed_root) / relative_path
        else:
            candidate = Path(self.allowed_root) / path.lstrip("/")
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
    
    def read_file(self, file_path):
        """Read the contents of a file from the workspace"""
        try:
            full_path = self.config.resolve_path(file_path)
            if not self.config.is_safe_path(full_path):
                return "ERROR: Access Denied. You may only access files in the workspace directory."
            
            with open(full_path, 'r') as f:
                return f.read()
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
            
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'w') as f:
                f.write(content)
            return f"Successfully wrote to {full_path}"
        except Exception as e:
            return f"ERROR: Failed to write file: {str(e)}"
    
    def list_files(self, directory):
        """List all files in a directory"""
        try:
            full_path = self.config.resolve_path(directory)
            if not self.config.is_safe_path(full_path):
                return "ERROR: Access Denied."
            
            if not os.path.isdir(full_path):
                return f"ERROR: Directory not found: {directory}"
            
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
    
    def check_syntax(self, file_path, language=None):
        """
        Check syntax of a file without executing it.
        Detects language automatically or uses provided language.
        """
        try:
            full_path = self.config.resolve_path(file_path)
            if not self.config.is_safe_path(full_path):
                return "ERROR: Access Denied."
            
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
            
            if not os.path.exists(full_path):
                return f"ERROR: File not found: {file_path}"
            
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
    
    def get_tool_definitions(self):
        """Return OpenAI-compatible tool definitions"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read the contents of a file from the workspace",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {
                                "type": "string",
                                "description": "Path to the file, e.g. /workspace/api.js"
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
                    "description": "List all files in a directory",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "directory": {
                                "type": "string",
                                "description": "Directory path to list"
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
                    "description": "Run linting on a file to find code quality issues",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {
                                "type": "string",
                                "description": "Path to the file to lint"
                            }
                        },
                        "required": ["file_path"]
                    }
                }
            }
        ]
    
    def execute_tool(self, function_name, function_args):
        """Execute a tool by name with given arguments"""
        try:
            if function_name == "read_file":
                return self.files.read_file(function_args.get("file_path", ""))
            
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
