"""
general_agent.py - Universal AI Agent Template

This is a general-purpose agent framework that can be extended for any role:
- Backend Engineer
- Frontend Developer  
- DevOps Engineer
- Data Engineer
- QA Automation
- etc.

To use this, instantiate with role-specific instructions.
"""

from openai import AzureOpenAI
import json
import os
import subprocess
import time
import random
import re
import shlex
from datetime import datetime
from dotenv import load_dotenv
from tooly import ToolRegistry, has_command_failed, is_done
from issues_tracker import get_issues_tracker

load_dotenv()

MODEL_CALL_DELAY_MIN = float(os.getenv("MODEL_CALL_DELAY_MIN", "1.0"))
MODEL_CALL_DELAY_MAX = float(os.getenv("MODEL_CALL_DELAY_MAX", "2.0"))
CONTEXT_PRUNE_SOFT_MAX_TOKENS = int(os.getenv("CONTEXT_PRUNE_SOFT_MAX_TOKENS", "120000"))
CONTEXT_PRUNE_HARD_MAX_TOKENS = int(os.getenv("CONTEXT_PRUNE_HARD_MAX_TOKENS", "220000"))
CONTEXT_PRUNE_SOFT_KEEP_RECENT = int(os.getenv("CONTEXT_PRUNE_SOFT_KEEP_RECENT", "60"))
CONTEXT_PRUNE_HARD_KEEP_RECENT = int(os.getenv("CONTEXT_PRUNE_HARD_KEEP_RECENT", "25"))
CONTEXT_PRUNE_SOFT_MAX_MESSAGES = int(os.getenv("CONTEXT_PRUNE_SOFT_MAX_MESSAGES", "120"))
AZURE_MODEL_DEPLOYMENT = os.getenv("AZURE_MODEL_DEPLOYMENT")
AGENT_TRACE_MODE = (os.getenv("AGENT_TRACE_MODE", "summary") or "summary").strip().lower()
AI_RESPONSES_LOG_DIR = os.getenv("AI_RESPONSES_LOG_DIR", "./agent_logs/ai_responses")

# Global references (set by orchestrator)
_BLACKBOARD = None

def set_blackboard(blackboard):
    """Set the global blackboard reference for agents to use"""
    global _BLACKBOARD
    _BLACKBOARD = blackboard

def set_layer_blackboard(layer_blackboard, agent_role, notebooks_dir):
    """Backward-compatible no-op. Context is now stored per-agent instance."""
    return


class CWDAwareToolRegistry:
    """Wrapper around ToolRegistry that makes tools workspace-aware"""
    
    def __init__(self, tool_registry, allowed_root, workspace_root=None):
        self.tool_registry = tool_registry
        self.allowed_root = allowed_root
        self.layer_blackboard = None
        self.agent_role = os.path.basename(os.path.normpath(allowed_root))
        self.service_bus = None
        self.notebooks_dir = None
        self.parallel_peers = []
        self.layer_blackboard_read_count = 0
        self.layer_blackboard_last_seen_count = 0
        self.layer_blackboard_last_seen_peer_count = 0
        self.layer_blackboard_post_count = 0
        self.layer_blackboard_post_after_read = False
        self.pending_bus_questions = {}
        self.last_bus_poll_count = 0
        self.layer_sleep = None
        self.sleep_requested = False
        self.read_operations = 0
        self.cross_workspace_reads = 0
        self.write_operations = 0
        self.upstream_reads_before_first_write = 0
        self.plan_announced = False
        self.todo_noted = False
        self.design_noted = False
        self.validation_actions = 0
        self.write_scope = "role"  # role | workspace
        self.preferred_output_roots = []
        self.primary_output_root = ""
        self.discovery_operations = 0
        self._last_discovery_signature = ""
        self._last_discovery_repeat_count = 0
        self.file_write_counts = {}
        self.max_writes_per_file = int(os.getenv("MAX_WRITES_PER_FILE", "6"))
        self.retry_fix_mode = False
        self.retry_existing_files = set()
        self.retry_allowed_new_paths = set()
        self.max_discovery_before_first_write = int(os.getenv("MAX_DISCOVERY_BEFORE_FIRST_WRITE", "14"))
        self.max_repeated_discovery_calls = int(os.getenv("MAX_REPEATED_DISCOVERY_CALLS", "3"))
        self.shared_write_roots = [
            s.strip().strip("/")
            for s in os.getenv("SHARED_WRITE_ROOTS", "shared,contracts").split(",")
            if s.strip()
        ]
        # If workspace_root not provided, derive it from allowed_root
        if workspace_root is None:
            workspace_root = os.path.dirname(allowed_root)
        self.workspace_root = workspace_root

    def _is_within(self, base_path: str, target_path: str) -> bool:
        """Robust boundary check using canonical resolved paths."""
        try:
            base_real = os.path.realpath(base_path)
            target_real = os.path.realpath(target_path)
            common = os.path.commonpath([base_real, target_real])
            return common == base_real
        except Exception:
            return False

    def _build_discovery_signature(self, function_name: str, function_args: dict) -> str:
        """Build a compact signature for discovery/read operations."""
        if function_name == "read_file":
            return f"read_file::{str(function_args.get('file_path', '')).strip()}"
        if function_name == "list_files":
            return f"list_files::{str(function_args.get('directory', '')).strip()}"
        if function_name == "search_files":
            pattern = function_args.get("pattern", function_args.get("query", ""))
            return f"search_files::{str(function_args.get('directory', '')).strip()}::{str(pattern).strip()}"
        if function_name == "search_in_files":
            return (
                "search_in_files::"
                f"{str(function_args.get('directory', '')).strip()}::"
                f"{str(function_args.get('query', '')).strip()}::"
                f"{str(function_args.get('file_pattern', '*')).strip()}"
            )
        return function_name

    def _check_discovery_loop_guard(self, function_name: str, function_args: dict):
        """Prevent repeated discovery loops and excessive pre-write exploration."""
        discovery_tools = {"read_file", "list_files", "search_files", "search_in_files"}
        if function_name not in discovery_tools:
            return None

        self.discovery_operations += 1
        signature = self._build_discovery_signature(function_name, function_args)

        if signature == self._last_discovery_signature:
            self._last_discovery_repeat_count += 1
        else:
            self._last_discovery_signature = signature
            self._last_discovery_repeat_count = 1

        if self._last_discovery_repeat_count > self.max_repeated_discovery_calls:
            return (
                "ERROR: Repeated discovery call loop detected. "
                "Stop repeating the same read/search/list request and pivot to implementation "
                "or a different verification action."
            )

        if self.write_operations == 0 and self.discovery_operations > self.max_discovery_before_first_write:
            return (
                "ERROR: Discovery budget exceeded before first write. "
                "Create initial implementation files now, then continue targeted validation."
            )

        return None
    
    def _resolve_read_path(self, file_path: str) -> str:
        """
        Resolve file paths to enable cross-workspace reads.
        
        Supports:
        - Local files: "file.js" → current workspace + "file.js"
        - Relative parent: "../other_agent/file.js" → ../other_agent/file.js resolved from workspace
        - Direct workspace: "database_architect/schema.sql" → ./workspace/database_architect/schema.sql
        
        Returns ABSOLUTE paths for all reads to avoid ambiguity.
        """
        # Normalize to forward slashes for consistency
        file_path = file_path.replace("\\", "/")
        
        workspace_abs = os.path.abspath(self.workspace_root)
        allowed_root_abs = os.path.abspath(self.allowed_root)
        
        # Case 1: Already absolute path
        if os.path.isabs(file_path):
            file_abs = os.path.abspath(file_path)
            if self._is_within(workspace_abs, file_abs):
                return file_abs
            raise ValueError(f"Path outside workspace: {file_path}")
        
        # Case 2: Relative parent path "../other_agent/file.js"
        # Go up from current workspace to shared workspace root, then into other agent
        if file_path.startswith("../"):
            # Resolve relative to the parent of allowed_root (which is workspace_root)
            resolved = os.path.normpath(os.path.join(self.allowed_root, file_path))
            resolved_abs = os.path.abspath(resolved)
            if not self._is_within(workspace_abs, resolved_abs):
                raise ValueError(f"Path traversal outside workspace: {file_path}")
            return resolved_abs
        
        # Case 3: Explicit workspace path "./workspace/..." or "workspace/..."
        if file_path == "./workspace" or file_path == "workspace":
            return workspace_abs
        if file_path.startswith("./workspace/"):
            resolved = os.path.join(workspace_abs, file_path[len("./workspace/"):])
            resolved_abs = os.path.abspath(resolved)
            if self._is_within(workspace_abs, resolved_abs):
                return resolved_abs
        if file_path.startswith("workspace/"):
            resolved = os.path.join(workspace_abs, file_path[len("workspace/"):])
            resolved_abs = os.path.abspath(resolved)
            if self._is_within(workspace_abs, resolved_abs):
                return resolved_abs

        # Case 4: Cross-workspace direct path "other_agent/file.js"
        # Only treat as cross-workspace if first segment is an existing workspace subdir.
        if "/" in file_path and not file_path.startswith("./"):
            first_segment = file_path.split("/", 1)[0]
            first_segment_abs = os.path.join(workspace_abs, first_segment)
            if os.path.isdir(first_segment_abs):
                resolved = os.path.join(workspace_abs, file_path)
                resolved_abs = os.path.abspath(resolved)
                if self._is_within(workspace_abs, resolved_abs):
                    return resolved_abs
        
        # Case 5: Local file in current workspace "file.js" or "./file.js"
        # Clean up the path
        if file_path.startswith("./"):
            file_path = file_path[2:]
        
        resolved = os.path.join(allowed_root_abs, file_path)
        resolved_abs = os.path.abspath(resolved)
        if self._is_within(allowed_root_abs, resolved_abs):
            return resolved_abs
        
        raise ValueError(f"Invalid path: {file_path}")
    
    def get_tool_definitions(self):
        """Get standard tool definitions"""
        tools = self.tool_registry.get_tool_definitions()
        
        # Add blackboard communication tools
        tools.append({
            "type": "function",
            "function": {
                "name": "announce_plan",
                "description": "Announce your work plan to the blackboard BEFORE starting work. Helps other agents understand what you're building and coordinate dependencies.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "plan": {
                            "type": "string",
                            "description": "Your implementation plan (what you will build)"
                        },
                        "deliverables": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of files/components you will create"
                        },
                        "dependencies": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "What you need from other agents (e.g., 'database schema', 'API endpoints')"
                        }
                    },
                    "required": ["plan", "deliverables"]
                }
            }
        })
        
        tools.append({
            "type": "function",
            "function": {
                "name": "update_blackboard",
                "description": "Post a summary of your completed work to the shared blackboard for other agents to see",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "Your summary of work completed (1-2 sentences)"
                        }
                    },
                    "required": ["content"]
                }
            }
        })
        
        # Issue tracking and collaboration tools
        tools.append({
            "type": "function",
            "function": {
                "name": "report_issue",
                "description": "Report a blocking issue that prevents progress. Alerts other agents to help solve it.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "component": {
                            "type": "string",
                            "description": "What component is blocked (e.g., 'database schema access')"
                        },
                        "description": {
                            "type": "string",
                            "description": "What went wrong and why it blocks you"
                        },
                        "severity": {
                            "type": "string",
                            "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
                            "description": "How critical (default: HIGH)"
                        },
                        "tried": {
                            "type": "string",
                            "description": "What have you already tried to fix it"
                        },
                        "needs_help_from": {
                            "type": "string",
                            "description": "Which agent could help (e.g., 'backend_engineer')"
                        },
                        "context": {
                            "type": "object",
                            "description": "Structured debugging context (files, failing routes, logs, stack traces, etc.)"
                        }
                    },
                    "required": ["component", "description"]
                }
            }
        })
        
        tools.append({
            "type": "function",
            "function": {
                "name": "read_issues",
                "description": "Read all current issues. Review this BEFORE starting work to understand what's blocking others.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "severity_filter": {
                            "type": "string",
                            "enum": ["ALL", "CRITICAL", "HIGH"],
                            "description": "Filter by severity"
                        }
                    }
                }
            }
        })
        
        tools.append({
            "type": "function",
            "function": {
                "name": "ask_agent",
                "description": "Ask another agent a direct question via Service Bus.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_name": {
                            "type": "string",
                            "description": "Name of agent to ask (e.g., 'backend_engineer')"
                        },
                        "question": {
                            "type": "string",
                            "description": "Your question"
                        }
                    },
                    "required": ["agent_name", "question"]
                }
            }
        })

        tools.append({
            "type": "function",
            "function": {
                "name": "read_agent_messages",
                "description": "Read incoming Service Bus messages addressed to you (questions/responses).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "max_messages": {
                            "type": "integer",
                            "description": "Maximum messages to read",
                            "default": 20
                        }
                    }
                }
            }
        })

        tools.append({
            "type": "function",
            "function": {
                "name": "reply_agent_message",
                "description": "Reply to a specific Service Bus question message ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message_id": {
                            "type": "string",
                            "description": "Question message ID you are replying to"
                        },
                        "to_agent": {
                            "type": "string",
                            "description": "Original sender to reply to"
                        },
                        "response": {
                            "type": "string",
                            "description": "Your response"
                        }
                    },
                    "required": ["message_id", "to_agent", "response"]
                }
            }
        })
        
        tools.append({
            "type": "function",
            "function": {
                "name": "check_blocking_issues",
                "description": "Check if your blocking issues have been resolved. Use this before giving up.",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        })
        
        # Layer blackboard tools for parallel agent coordination
        tools.append({
            "type": "function",
            "function": {
                "name": "post_to_layer_blackboard",
                "description": "Post to the layer blackboard to coordinate with parallel agents executing in this layer",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Your coordination message (implementation details, blockers, what you're building)"
                        }
                    },
                    "required": ["message"]
                }
            }
        })

        tools.append({
            "type": "function",
            "function": {
                "name": "read_layer_blackboard",
                "description": "Read current messages on the layer blackboard from parallel agents in this layer",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        })

        tools.append({
            "type": "function",
            "function": {
                "name": "sleep_agent",
                "description": "Pause yourself if blocked by a same-layer dependency. Use only when you cannot proceed without peer work.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {
                            "type": "string",
                            "description": "Blocking reason and what is needed to continue"
                        },
                        "waiting_for_agent": {
                            "type": "string",
                            "description": "Peer agent expected to unblock you",
                            "default": ""
                        }
                    },
                    "required": ["reason"]
                }
            }
        })

        tools.append({
            "type": "function",
            "function": {
                "name": "wake_agent",
                "description": "Wake a sleeping peer after you fixed the blocker they were waiting on.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_name": {
                            "type": "string",
                            "description": "Peer agent role name to wake"
                        },
                        "resolution": {
                            "type": "string",
                            "description": "What was fixed so they can resume"
                        }
                    },
                    "required": ["agent_name", "resolution"]
                }
            }
        })
        
        # Notebook tools for private notes/planning
        tools.append({
            "type": "function",
            "function": {
                "name": "write_to_notebook",
                "description": "Write to your personal notebook (private file for your thoughts, TODO list, decisions)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "What to write: TODO list, decisions, implementation details, assumptions"
                        },
                        "section": {
                            "type": "string",
                            "description": "Section name (e.g., 'TODO', 'DECISIONS', 'NOTES', 'ASSUMPTIONS')",
                            "default": "NOTES"
                        }
                    },
                    "required": ["content"]
                }
            }
        })
        
        tools.append({
            "type": "function",
            "function": {
                "name": "read_notebook",
                "description": "Read your personal notebook to review what you've planned",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        })
        
        return tools
    
    def execute_tool(self, function_name, function_args):
        """Execute a tool, handling CWD context and special tools"""
        role = self.agent_role or os.path.basename(os.path.normpath(self.allowed_root))

        loop_guard_error = self._check_discovery_loop_guard(function_name, function_args)
        if loop_guard_error:
            return loop_guard_error
        
        # Handle plan announcements (planning phase before work)
        if function_name == "announce_plan":
            if _BLACKBOARD is None:
                return "ERROR: Blackboard not initialized"
            
            plan = function_args.get("plan", "")
            deliverables = function_args.get("deliverables", [])
            dependencies = function_args.get("dependencies", [])
            
            # Format plan announcement
            announcement = f"PLAN: {plan}\n"
            if deliverables:
                announcement += f"Deliverables: {', '.join(deliverables)}\n"
            if dependencies:
                announcement += f"Needs from others: {', '.join(dependencies)}"
            
            try:
                _BLACKBOARD.post(role, "Discussions", announcement)
                self.plan_announced = True
                return f"✅ Plan announced to blackboard"
            except Exception as e:
                return f"ERROR announcing plan: {str(e)}"
        
        # Handle blackboard updates
        if function_name == "update_blackboard":
            if _BLACKBOARD is None:
                return "ERROR: Blackboard not initialized"
            
            content = function_args.get("content", "")
            
            try:
                _BLACKBOARD.post(role, "Implementation plan", content)
                return f"✅ Posted to blackboard: {content[:100]}..."
            except Exception as e:
                return f"ERROR posting to blackboard: {str(e)}"
        
        # Handle issue reporting
        if function_name == "report_issue":
            component = function_args.get("component", "")
            description = function_args.get("description", "")
            severity = function_args.get("severity", "HIGH")
            tried = function_args.get("tried", "")
            needs_help = function_args.get("needs_help_from", "")
            context = function_args.get("context", {})
            if not isinstance(context, dict):
                context = {}
            
            # Report to both blackboard and issues tracker
            issue_msg = f"🚨 [{severity}] {component}: {description}"
            if tried:
                issue_msg += f" | Tried: {tried}"
            if needs_help:
                issue_msg += f" | Needs: {needs_help}"
            
            try:
                if _BLACKBOARD:
                    _BLACKBOARD.post(role, "Issues", issue_msg)
                
                # Also report to issues tracker (JSON file)
                issues_tracker = get_issues_tracker()
                issue = issues_tracker.report_issue(
                    component=component,
                    description=description,
                    severity=severity,
                    reported_by=role,
                    assigned_to=needs_help if needs_help else "unassigned",
                    tried=tried,
                    context=context,
                )
                
                return f"✅ Issue reported: [{severity}] {component}"
            except Exception as e:
                return f"ERROR reporting issue: {str(e)}"
        
        # Handle reading issues
        if function_name == "read_issues":
            try:
                issues_tracker = get_issues_tracker()
                open_issues = issues_tracker.get_open_issues()
                if not open_issues:
                    # Fallback to blackboard section for backward compatibility
                    if _BLACKBOARD is not None:
                        issues = _BLACKBOARD.read_section("Issues")
                        if issues and "empty" not in issues.lower():
                            return f"📋 Current Issues:\n{issues}"
                    return "✅ No open issues at this time."

                output = "📋 Current Issues:\n"
                for issue in open_issues:
                    output += f"- [#{issue['id']}] [{issue['severity']}] {issue['component']}\n"
                    output += f"  Assigned to: {issue['assigned_to']}\n"
                    output += f"  {issue['description']}\n"
                return output
            except Exception as e:
                return f"ERROR reading issues: {str(e)}"
        
        # Handle asking other agents questions
        if function_name == "ask_agent":
            agent_name = function_args.get("agent_name", "")
            question = function_args.get("question", "")
            
            try:
                if self.service_bus is None or not self.service_bus.is_enabled():
                    return "ERROR: Service Bus is not configured. Cannot send direct agent questions."

                message_id = self.service_bus.send_question(role, agent_name, question)
                if isinstance(message_id, str) and message_id.startswith("ERROR:"):
                    return message_id
                return f"✅ Question sent to {agent_name} via Service Bus (id: {message_id})"
            except Exception as e:
                return f"ERROR posting question: {str(e)}"

        if function_name == "read_agent_messages":
            if self.service_bus is None or not self.service_bus.is_enabled():
                return "ERROR: Service Bus is not configured."
            try:
                max_messages = int(function_args.get("max_messages", 20) or 20)
                messages = self.service_bus.receive_for_agent(role, max_messages=max_messages, wait_seconds=1.0)
                self.last_bus_poll_count += len(messages)

                if not messages:
                    return "✅ No new Service Bus messages."

                lines = [f"📨 Received {len(messages)} Service Bus message(s):"]
                for m in messages:
                    msg_id = m.get("id", "unknown")
                    msg_type = m.get("type", "unknown")
                    from_agent = m.get("from_agent", "unknown")
                    to_agent = m.get("to_agent", "unknown")
                    content = m.get("content", "")

                    if msg_type == "question":
                        self.pending_bus_questions[msg_id] = m
                        lines.append(f"- [question] {msg_id} from {from_agent} to {to_agent}: {content}")
                    elif msg_type == "response":
                        lines.append(f"- [response] {msg_id} from {from_agent} to {to_agent}: {content} (FYI: do not reply)")
                    else:
                        lines.append(f"- [{msg_type}] {msg_id} from {from_agent} to {to_agent}: {content}")

                return "\n".join(lines)
            except Exception as e:
                return f"ERROR reading Service Bus messages: {str(e)}"

        if function_name == "reply_agent_message":
            if self.service_bus is None or not self.service_bus.is_enabled():
                return "ERROR: Service Bus is not configured."
            try:
                message_id = function_args.get("message_id", "")
                to_agent = function_args.get("to_agent", "")
                response = function_args.get("response", "")
                if not message_id or not to_agent or not response:
                    return "ERROR: message_id, to_agent, and response are required"

                pending = self.pending_bus_questions.get(message_id)
                if not pending:
                    return (
                        "ERROR: message_id is not a pending question. "
                        "Only question messages from read_agent_messages() can be replied to."
                    )

                expected_to_agent = pending.get("from_agent", "")
                if expected_to_agent and to_agent != expected_to_agent:
                    return (
                        f"ERROR: invalid to_agent for message_id {message_id}. "
                        f"Expected to_agent='{expected_to_agent}'."
                    )

                sent_id = self.service_bus.send_response(role, to_agent, message_id, response)
                if isinstance(sent_id, str) and sent_id.startswith("ERROR:"):
                    return sent_id

                if message_id in self.pending_bus_questions:
                    del self.pending_bus_questions[message_id]
                return f"✅ Reply sent to {to_agent} (id: {sent_id})"
            except Exception as e:
                return f"ERROR sending Service Bus reply: {str(e)}"
        
        # Handle checking if blocking issues are resolved
        if function_name == "check_blocking_issues":
            try:
                issues_tracker = get_issues_tracker()
                blocking = issues_tracker.get_blocking_issues(role)
                
                if not blocking:
                    return "✅ No blocking issues for you!"
                
                output = f"⚠️ You still have {len(blocking)} blocking issue(s):\n"
                for issue in blocking:
                    output += f"\n[{issue['id']}] {issue['severity']} - {issue['component']}\n"
                    output += f"    Assigned to: {issue['assigned_to']}\n"
                    output += f"    {issue['description']}\n"
                
                return output
            except Exception as e:
                return f"ERROR checking blocking issues: {str(e)}"

        if function_name == "sleep_agent":
            if self.layer_sleep is None:
                return "ERROR: Sleep mode is not available outside parallel layer execution"

            reason = function_args.get("reason", "").strip()
            waiting_for = function_args.get("waiting_for_agent", "").strip()
            if not reason:
                return "ERROR: sleep_agent requires a non-empty reason"
            if not waiting_for:
                return "ERROR: sleep_agent requires waiting_for_agent to avoid ambiguous deadlocks"
            peers = set(self.parallel_peers or [])
            if waiting_for not in peers:
                return (
                    "ERROR: sleep_agent waiting_for_agent must be an active peer in this layer. "
                    f"Got '{waiting_for}', peers: {', '.join(sorted(peers)) or 'none'}"
                )

            try:
                self.layer_sleep.request_sleep(self.agent_role or role, reason, waiting_for)
                self.sleep_requested = True
                if self.layer_blackboard is not None:
                    msg = f"SLEEP: blocked. Waiting for {waiting_for or 'peer update'}. Reason: {reason}"
                    self.layer_blackboard.post(self.agent_role or role, msg)
                return f"✅ Sleep requested. Waiting for wake-up signal. Reason: {reason}"
            except Exception as e:
                return f"ERROR entering sleep mode: {str(e)}"

        if function_name == "wake_agent":
            if self.layer_sleep is None:
                return "ERROR: wake_agent is not available outside parallel layer execution"

            agent_name = function_args.get("agent_name", "").strip()
            resolution = function_args.get("resolution", "").strip()
            if not agent_name or not resolution:
                return "ERROR: wake_agent requires agent_name and resolution"

            try:
                self.layer_sleep.wake(agent_name, self.agent_role or role, resolution)
                if self.layer_blackboard is not None:
                    msg = f"WAKE: notified {agent_name}. Resolution: {resolution}"
                    self.layer_blackboard.post(self.agent_role or role, msg)
                return f"✅ Wake signal sent to {agent_name}"
            except Exception as e:
                return f"ERROR waking agent: {str(e)}"
        
        # For command tools, we need to run with correct CWD
        if function_name == "run_command":
            cmd = function_args.get("command", "")
            self.validation_actions += 1
            if getattr(self, "write_scope", "role") == "workspace":
                cmd_text = str(cmd or "")
                token_block = re.compile(r"(^|[\\s;&|()])(?:rm|curl|sudo|dd)(?=$|[\\s;&|()])", re.IGNORECASE)
                if token_block.search(cmd_text) or ":/" in cmd_text:
                    return "ERROR: Access Denied. The requested command contains forbidden keywords!"

                cwd_arg = function_args.get("cwd")
                if cwd_arg:
                    if os.path.isabs(str(cwd_arg)):
                        workspace_cwd = os.path.abspath(str(cwd_arg))
                    else:
                        workspace_cwd = os.path.abspath(os.path.join(self.workspace_root, str(cwd_arg)))
                else:
                    workspace_cwd = os.path.abspath(self.workspace_root)
                workspace_abs = os.path.abspath(self.workspace_root)
                if not self._is_within(workspace_abs, workspace_cwd):
                    return "ERROR: Unsafe working directory"

                if re.search(r"[;&|`]|\$\(|\n", cmd_text):
                    return "ERROR: Complex shell expressions are not allowed. Use a single direct command."

                timeout = 60
                try:
                    timeout = int(getattr(getattr(self.tool_registry, "config", None), "timeout", 60) or 60)
                except Exception:
                    timeout = 60

                try:
                    cmd_parts = shlex.split(cmd_text)
                    if not cmd_parts:
                        return "ERROR: Empty command"
                    result = subprocess.run(
                        cmd_parts,
                        shell=False,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        cwd=workspace_cwd
                    )
                    status = "SUCCESS" if result.returncode == 0 else "FAILED"
                    return (
                        f"STATUS: {status}\nEXIT_CODE: {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
                    )
                except subprocess.TimeoutExpired:
                    return f"ERROR: Command timed out after {timeout} seconds."
                except Exception as e:
                    return f"ERROR: {str(e)}"

            result = self.tool_registry.execute_tool(function_name, function_args)
            return result
        
        # For syntax checking, ensure it runs in the right directory
        if function_name == "check_syntax":
            file_path = function_args.get("file_path", "")
            language = (function_args.get("language", "") or "").strip().lower()
            self.validation_actions += 1
            
            # Resolve path (allows cross-workspace reads)
            try:
                full_path = self._resolve_read_path(file_path)
            except ValueError as e:
                return f"ERROR: {str(e)}"
            
            if not os.path.exists(full_path):
                return f"ERROR: File not found: {file_path}"
            
            # Run syntax check from the agent's workspace directory
            try:
                _, ext = os.path.splitext(str(file_path).lower())
                if not language:
                    if ext in {".js", ".jsx", ".mjs", ".cjs"}:
                        language = "javascript"
                    elif ext in {".ts"}:
                        language = "typescript"
                    elif ext in {".tsx"}:
                        language = "tsx"
                    elif ext in {".sql"}:
                        language = "sql"

                # Node --check cannot parse JSX/TSX directly.
                if ext in {".jsx", ".tsx"} or language in {"jsx", "tsx"}:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    if content.count("{") != content.count("}"):
                        return f"❌ POTENTIAL SYNTAX ERROR: Mismatched curly braces in {file_path}"
                    if content.count("(") != content.count(")"):
                        return f"❌ POTENTIAL SYNTAX ERROR: Mismatched parentheses in {file_path}"
                    if content.count("[") != content.count("]"):
                        return f"❌ POTENTIAL SYNTAX ERROR: Mismatched square brackets in {file_path}"
                    return f"✅ Syntax OK: JSX/TSX heuristic check passed for {file_path}"

                if language == "javascript":
                    result = subprocess.run(
                        ["node", "--check", full_path],
                        cwd=self.allowed_root,
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    if result.returncode == 0:
                        return f"✅ Syntax OK: {file_path}"
                    else:
                        return f"❌ SYNTAX ERROR:\n{result.stderr}"
                
                elif language == "sql":
                    return f"⚠️ Language '{language}' syntax checking not yet implemented"
                
                else:
                    return f"⚠️ Language '{language}' syntax checking not supported"
            
            except subprocess.TimeoutExpired:
                return f"ERROR: Syntax check timed out for {file_path}"
            except Exception as e:
                return f"ERROR: Failed to check syntax: {str(e)}"
        
        # For read operations, use cross-workspace-aware path resolution
        if function_name == "read_file":
            file_path = function_args.get("file_path", "")
            try:
                resolved_path = self._resolve_read_path(file_path)
                self.read_operations += 1
                allowed_abs = os.path.abspath(self.allowed_root)
                if os.path.isabs(resolved_path) and not self._is_within(allowed_abs, os.path.abspath(resolved_path)):
                    self.cross_workspace_reads += 1
                    if self.write_operations == 0:
                        self.upstream_reads_before_first_write += 1
                
                # If it's a cross-workspace read (absolute path), handle it directly
                if os.path.isabs(resolved_path):
                    if not os.path.exists(resolved_path):
                        return f"ERROR: File not found: {file_path}"
                    try:
                        with open(resolved_path, 'r') as f:
                            content = f.read()
                        
                        # CONTEXT PROTECTION: Truncate very large files to prevent token overflow
                        # 50KB limit per file read to prevent context explosion
                        MAX_FILE_READ_BYTES = 50000
                        if len(content) > MAX_FILE_READ_BYTES:
                            truncated_content = content[:MAX_FILE_READ_BYTES]
                            truncated_msg = f"\n\n... [FILE TRUNCATED - Original size: {len(content)} bytes, showing first {MAX_FILE_READ_BYTES} bytes] ..."
                            return truncated_content + truncated_msg
                        
                        return content
                    except Exception as e:
                        return f"ERROR: Could not read file: {str(e)}"
                else:
                    # Local read - let tooly handle it
                    function_args["file_path"] = resolved_path
            except ValueError as e:
                return f"ERROR: {str(e)}"
        
        if function_name == "list_files":
            directory = function_args.get("directory", "")
            try:
                resolved_path = self._resolve_read_path(directory)
                self.read_operations += 1
                allowed_abs = os.path.abspath(self.allowed_root)
                if os.path.isabs(resolved_path) and not self._is_within(allowed_abs, os.path.abspath(resolved_path)):
                    self.cross_workspace_reads += 1
                    if self.write_operations == 0:
                        self.upstream_reads_before_first_write += 1
                
                # If it's a cross-workspace read (absolute path), handle it directly
                if os.path.isabs(resolved_path):
                    if not os.path.isdir(resolved_path):
                        return f"ERROR: Directory not found: {directory}"
                    try:
                        files = os.listdir(resolved_path)
                        return f"✅ Files in {directory}:\n" + "\n".join(files)
                    except Exception as e:
                        return f"ERROR: Could not list directory: {str(e)}"
                else:
                    # Local read - let tooly handle it
                    function_args["directory"] = resolved_path
            except ValueError as e:
                return f"ERROR: {str(e)}"
        
        # For search_files with cross-workspace directory support
        if function_name == "search_files":
            directory = function_args.get("directory", "")
            pattern = function_args.get("pattern", "")
            if not pattern:
                pattern = function_args.get("query", "")
                if pattern:
                    function_args["pattern"] = pattern
            try:
                resolved_path = self._resolve_read_path(directory)
                self.read_operations += 1
                allowed_abs = os.path.abspath(self.allowed_root)
                if os.path.isabs(resolved_path) and not self._is_within(allowed_abs, os.path.abspath(resolved_path)):
                    self.cross_workspace_reads += 1
                    if self.write_operations == 0:
                        self.upstream_reads_before_first_write += 1
                
                # If it's a cross-workspace search (absolute path), handle it directly
                if os.path.isabs(resolved_path):
                    if not os.path.isdir(resolved_path):
                        return f"ERROR: Directory not found: {directory}"
                    try:
                        import fnmatch
                        matching_files = []
                        for root, dirs, files in os.walk(resolved_path):
                            for file in files:
                                if fnmatch.fnmatch(file, pattern):
                                    rel_path = os.path.relpath(os.path.join(root, file), resolved_path)
                                    matching_files.append(rel_path)
                        
                        if not matching_files:
                            return f"✅ No files matching '{pattern}' in {directory}"
                        return f"✅ Files matching '{pattern}' in {directory}:\n" + "\n".join(matching_files)
                    except Exception as e:
                        return f"ERROR: Could not search directory: {str(e)}"
                else:
                    # Local search - let tooly handle it
                    function_args["directory"] = resolved_path
            except ValueError as e:
                return f"ERROR: {str(e)}"
        
        # For search_in_files with cross-workspace support
        if function_name == "search_in_files":
            directory = function_args.get("directory", "")
            query = function_args.get("query", "")
            file_pattern = function_args.get("file_pattern", "*")
            try:
                resolved_path = self._resolve_read_path(directory)
                self.read_operations += 1
                allowed_abs = os.path.abspath(self.allowed_root)
                if os.path.isabs(resolved_path) and not self._is_within(allowed_abs, os.path.abspath(resolved_path)):
                    self.cross_workspace_reads += 1
                    if self.write_operations == 0:
                        self.upstream_reads_before_first_write += 1
                
                # If it's a cross-workspace search (absolute path), handle it directly
                if os.path.isabs(resolved_path):
                    if not os.path.isdir(resolved_path):
                        return f"ERROR: Directory not found: {directory}"
                    try:
                        import fnmatch
                        results = []
                        query_pattern = re.compile(query, re.IGNORECASE)
                        
                        for root, dirs, files in os.walk(resolved_path):
                            for file in files:
                                if fnmatch.fnmatch(file, file_pattern):
                                    file_path = os.path.join(root, file)
                                    try:
                                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                            for line_num, line in enumerate(f, 1):
                                                if query_pattern.search(line):
                                                    rel_path = os.path.relpath(file_path, resolved_path)
                                                    results.append(f"{rel_path}:{line_num}: {line.strip()}")
                                                    if len(results) >= 50:  # Limit to 50 matches
                                                        break
                                            if len(results) >= 50:
                                                break
                                    except:
                                        pass
                        
                        if not results:
                            return f"✅ No matches for '{query}' in {directory}"
                        return f"✅ Found {len(results)} matches for '{query}':\n" + "\n".join(results[:50])
                    except Exception as e:
                        return f"ERROR: Could not search files: {str(e)}"
                else:
                    # Local search - let tooly handle it
                    function_args["directory"] = resolved_path
            except ValueError as e:
                return f"ERROR: {str(e)}"
        
        # For write operations, keep STRICT security - files only to agent's directory
        elif function_name == "write_file":
            file_path = function_args.get("file_path", "").replace("\\", "/")
            role_name = os.path.basename(os.path.normpath(self.allowed_root))
            workspace_abs = os.path.abspath(self.workspace_root)
            allowed_abs = os.path.abspath(self.allowed_root)
            write_scope = getattr(self, "write_scope", "role")

            # Normalize absolute write path to relative if inside allowed_root
            if os.path.isabs(file_path):
                file_abs = os.path.abspath(file_path)
                if write_scope == "workspace":
                    if not self._is_within(workspace_abs, file_abs):
                        return f"ERROR: Cannot write outside workspace: {file_path}"
                    file_path = os.path.relpath(file_abs, workspace_abs).replace("\\", "/")
                else:
                    if not self._is_within(allowed_abs, file_abs):
                        return f"ERROR: Cannot write outside your workspace directory: {file_path}"
                    file_path = os.path.relpath(file_abs, allowed_abs).replace("\\", "/")

            # Strip accidental workspace prefixes to avoid nested workspace folders.
            if write_scope == "workspace":
                for prefix in ["./workspace/", "workspace/"]:
                    if file_path.startswith(prefix):
                        file_path = file_path[len(prefix):]
            else:
                for prefix in [
                    f"./workspace/{role_name}/",
                    f"workspace/{role_name}/",
                    f"{role_name}/"
                ]:
                    if file_path.startswith(prefix):
                        file_path = file_path[len(prefix):]

            # Reject workspace-prefixed writes unless workspace write scope is enabled.
            if write_scope != "workspace" and (file_path.startswith("./workspace/") or file_path.startswith("workspace/")):
                return f"ERROR: write_file must use paths relative to your workspace root, got: {function_args.get('file_path', '')}"

            if file_path.startswith("./"):
                file_path = file_path[2:]

            if write_scope == "workspace":
                allowed_rel = os.path.relpath(allowed_abs, workspace_abs).replace("\\", "/").strip("./")
                primary_root = str(getattr(self, "primary_output_root", "") or "").replace("\\", "/").strip("/")
                preferred_roots = [
                    str(r).strip().strip("/")
                    for r in (getattr(self, "preferred_output_roots", []) or [])
                    if str(r).strip()
                ]
                allowed_roots = set(preferred_roots)
                if primary_root:
                    allowed_roots.add(primary_root)
                if allowed_rel:
                    allowed_roots.add(allowed_rel)

                def _within_root(path_value: str, root_value: str) -> bool:
                    root_norm = (root_value or "").strip("/")
                    if not root_norm:
                        return True
                    return path_value == root_norm or path_value.startswith(root_norm + "/")

                requested_rel = file_path.replace("\\", "/").strip("/")

                # If model emits project-name wrappers like
                # "bakery_website/backend/...", strip that wrapper so all
                # writes stay directly under workspace production roots.
                common_roots = {
                    "backend", "frontend", "database", "api", "contracts",
                    "devops", "security", "tests", "docs", "shared", "config",
                    "migrations", "scripts", "infra", "qa", "ml"
                }
                parts = [p for p in requested_rel.split("/") if p]
                if len(parts) >= 2 and parts[1].lower() in common_roots:
                    first = parts[0].lower()
                    first_is_allowed = any(first == r.lower() for r in allowed_roots if isinstance(r, str) and r)
                    first_is_shared = any(first == r.lower() for r in self.shared_write_roots if isinstance(r, str) and r)
                    first_is_common = first in common_roots
                    if not first_is_allowed and not first_is_shared and not first_is_common:
                        requested_rel = "/".join(parts[1:])

                # Collapse repeated adjacent segments anywhere in the path,
                # e.g. backend/backend/routes -> backend/routes.
                def _collapse_adjacent_duplicates(path_value: str) -> str:
                    parts = [p for p in path_value.split("/") if p]
                    if not parts:
                        return ""
                    collapsed = []
                    for p in parts:
                        if not collapsed or collapsed[-1] != p:
                            collapsed.append(p)
                    return "/".join(collapsed)

                requested_rel = _collapse_adjacent_duplicates(requested_rel)
                candidate_rels = []
                if requested_rel:
                    candidate_rels.append(requested_rel)
                if allowed_rel and requested_rel:
                    if requested_rel != allowed_rel and not requested_rel.startswith(allowed_rel + "/"):
                        candidate_rels.append(f"{allowed_rel}/{requested_rel}")

                selected_rel = None
                selected_received = requested_rel
                workspace_norm = os.path.normpath(self.workspace_root)
                for rel in candidate_rels:
                    # Collapse accidental duplicate leading root segment: root/root/... -> root/...
                    rel_norm = rel.replace("\\", "/").strip("/")
                    for root in list(allowed_roots):
                        root_norm = (root or "").strip("/")
                        if not root_norm:
                            continue
                        doubled = f"{root_norm}/{root_norm}/"
                        if rel_norm.startswith(doubled):
                            rel_norm = root_norm + "/" + rel_norm[len(doubled):]
                    rel = rel_norm

                    full_path = os.path.normpath(os.path.join(self.workspace_root, rel))
                    if not self._is_within(workspace_norm, full_path):
                        continue

                    file_rel = os.path.relpath(full_path, os.path.abspath(self.workspace_root)).replace("\\", "/").strip("/")
                    in_owned_root = any(_within_root(file_rel, root) for root in allowed_roots)
                    in_shared_root = any(_within_root(file_rel, root) for root in self.shared_write_roots)
                    if (not allowed_roots) or in_owned_root or in_shared_root:
                        selected_rel = rel
                        selected_received = file_rel
                        break

                if selected_rel is None:
                    allowed_list = sorted([r for r in allowed_roots if r] + [r for r in self.shared_write_roots if r])
                    return (
                        "ERROR: Write path violates ownership policy. "
                        f"Allowed roots: {', '.join(allowed_list)}. "
                        f"Received: {selected_received}"
                    )

                # IMPORTANT: perform workspace-scope writes directly to avoid
                # ToolConfig re-rooting paths under allowed_root (which causes
                # duplicated directories like backend/backend).
                try:
                    final_abs = os.path.normpath(os.path.join(self.workspace_root, selected_rel))
                    rel_key = os.path.relpath(final_abs, os.path.abspath(self.workspace_root)).replace("\\", "/")

                    current_writes = int(self.file_write_counts.get(rel_key, 0) or 0)
                    if current_writes >= self.max_writes_per_file:
                        return (
                            "ERROR: Rewrite loop detected for file: "
                            f"{rel_key} (writes: {current_writes}). "
                            "Stop rewriting this file and implement remaining missing files/routes."
                        )

                    workspace_norm = os.path.normpath(self.workspace_root)
                    if not self._is_within(workspace_norm, final_abs):
                        return f"ERROR: Cannot write outside workspace: {selected_rel}"

                    os.makedirs(os.path.dirname(final_abs), exist_ok=True)
                    with open(final_abs, "w", encoding="utf-8") as f:
                        f.write(function_args.get("content", ""))

                    self.write_operations += 1
                    self.file_write_counts[rel_key] = current_writes + 1
                    return f"Successfully wrote to {final_abs}"
                except Exception as e:
                    return f"ERROR: Failed to write file: {str(e)}"
            else:
                full_path = os.path.normpath(os.path.join(self.allowed_root, file_path))
                if not self._is_within(os.path.normpath(self.allowed_root), full_path):
                    return f"ERROR: Cannot write outside your workspace directory: {file_path}"
                rel_key = os.path.relpath(full_path, os.path.abspath(self.workspace_root)).replace("\\", "/")

                current_writes = int(self.file_write_counts.get(rel_key, 0) or 0)
                if current_writes >= self.max_writes_per_file:
                    return (
                        "ERROR: Rewrite loop detected for file: "
                        f"{rel_key} (writes: {current_writes}). "
                        "Stop rewriting this file and implement remaining missing files/routes."
                    )
                self.file_write_counts[rel_key] = current_writes + 1
                function_args["file_path"] = file_path
        
        # Handle layer blackboard coordination
        if function_name == "post_to_layer_blackboard":
            if self.layer_blackboard is None:
                return "ERROR: Layer blackboard not initialized (you may be in a layer with no parallel agents)"
            
            message = function_args.get("message", "")
            if not message:
                return "ERROR: Message cannot be empty"
            
            try:
                self.layer_blackboard.post(self.agent_role or "unknown", message)
                self.plan_announced = True
                self.layer_blackboard_post_count += 1
                if self.layer_blackboard_read_count > 0:
                    self.layer_blackboard_post_after_read = True
                return f"✅ Posted to layer blackboard: {message[:80]}..."
            except Exception as e:
                return f"ERROR posting to layer blackboard: {str(e)}"

        # Handle layer blackboard reading
        if function_name == "read_layer_blackboard":
            if self.layer_blackboard is None:
                return "Layer blackboard is not initialized for this layer."
            try:
                content = self.layer_blackboard.read_all()
                self.layer_blackboard_read_count += 1
                if hasattr(self.layer_blackboard, "message_count"):
                    self.layer_blackboard_last_seen_count = self.layer_blackboard.message_count()
                if hasattr(self.layer_blackboard, "peer_message_count"):
                    self.layer_blackboard_last_seen_peer_count = self.layer_blackboard.peer_message_count(self.agent_role or "unknown")
                return content
            except Exception as e:
                return f"ERROR reading layer blackboard: {str(e)}"
        
        # Handle notebook writing
        if function_name == "write_to_notebook":
            if self.notebooks_dir is None:
                return "ERROR: Notebooks directory not initialized"
            
            content = function_args.get("content", "")
            section = function_args.get("section", "NOTES")
            section_upper = str(section).upper()
            
            if not content:
                return "ERROR: Content cannot be empty"

            content_lower = str(content).lower()
            if section_upper == "TODO" or "todo" in content_lower:
                self.todo_noted = True
            design_keywords = [
                "flow", "structure", "directory", "component", "layout",
                "screen", "route", "endpoint", "state", "api contract"
            ]
            if section_upper in {"ARCHITECTURE", "FLOW", "DECISIONS"} or any(k in content_lower for k in design_keywords):
                self.design_noted = True
            
            try:
                # Create notebook file for this agent
                notebook_path = os.path.join(self.notebooks_dir, f"{self.agent_role or 'unknown'}.md")
                
                # Read existing notebook or create new
                if os.path.exists(notebook_path):
                    with open(notebook_path, 'a') as f:
                        f.write(f"\n\n## {section}\n{content}")
                else:
                    with open(notebook_path, 'w') as f:
                        f.write(f"# {self.agent_role or 'Agent'} Notebook\n\n## {section}\n{content}")
                
                return f"✅ Written to notebook [{section}]: {content[:80]}..."
            except Exception as e:
                return f"ERROR writing to notebook: {str(e)}"
        
        # Handle notebook reading
        if function_name == "read_notebook":
            if self.notebooks_dir is None:
                return "ERROR: Notebooks directory not initialized"
            
            try:
                notebook_path = os.path.join(self.notebooks_dir, f"{self.agent_role or 'unknown'}.md")
                
                if not os.path.exists(notebook_path):
                    return "Notebook is empty. Start by writing_to_notebook()."
                
                with open(notebook_path, 'r') as f:
                    content = f.read()
                
                return content
            except Exception as e:
                return f"ERROR reading notebook: {str(e)}"
        
        # Default: use standard tool registry
        result = self.tool_registry.execute_tool(function_name, function_args)
        if function_name == "write_file" and isinstance(result, str) and "Successfully wrote to" in result:
            self.write_operations += 1
        return result


class GeneralAgent:
    """
    Universal AI Agent that can be configured for any role.
    
    Usage:
        agent = GeneralAgent(
            role="Backend Engineer",
            specific_instructions="Your role-specific instructions here"
        )
        result = agent.execute(task_description="Your task", context={})
    """
    
    # Generic system prompt that works for any agent
    GENERIC_SYSTEM_PROMPT = """You are {role} - an expert at delivering working code efficiently.

ROLE: {role_description}

═══════════════════════════════════════════════════════════════════════════════
GOLDEN RULES (Non-Negotiable)
═══════════════════════════════════════════════════════════════════════════════

1. ✅ CREATE FILES - Output with 0 files = FAILURE
2. ✅ NO RETRY LOOPS - Max 2 attempts on same error, then PIVOT to different approach
3. ✅ CONTRACTS FIRST - Read and align with upstream code/contracts before implementing
4. ✅ END WITH [READY_FOR_VERIFICATION] - When complete, output this exact token
5. ✅ KEEP RESPONSES SHORT - 1-2 sentences per thought, not paragraphs
6. ✅ BATCH OPERATIONS - Write multiple files in one iteration, not sequentially
7. ✅ DOCUMENT YOUR OUTPUT - Add inline comments/docs and create README.md in your workspace
8. ✅ PLAN FIDELITY - Write and follow a concrete file/flow plan; if you deviate, note why in notebook

═══════════════════════════════════════════════════════════════════════════════
WORK MODE (Iterative, not Waterfall)
═══════════════════════════════════════════════════════════════════════════════

Use a BUILD → VALIDATE → REFINE loop. You may revisit planning whenever needed.

1) PLAN QUICKLY (once, then update only if changed)
    • write_to_notebook(section="TODO") with concrete files/steps
    • write_to_notebook(section="ARCHITECTURE") with directory + flow/contracts
    • announce_plan() once with intended deliverables

2) BUILD WITH FILE-FIRST SOURCE OF TRUTH
    • Read upstream code first (list_files/search_in_files/read_file)
    • Prefer reading files over asking peers when code already answers the question
    • Write multiple deliverables per iteration (batch write_file calls)
    • Create dependency manifest + README.md

3) VALIDATE + REFINE
    • Non-QA: run targeted checks (run_command/check_syntax)
    • QA: run/fix tests with realistic imports and runnable syntax
    • If a contract mismatch is found, fix code first, then post concise updates

4) COMPLETE
    • update_blackboard() summary
    • Output [READY_FOR_VERIFICATION]

═══════════════════════════════════════════════════════════════════════════════
COMMUNICATION CHANNELS
═══════════════════════════════════════════════════════════════════════════════

Three places to post:

1. LAYER BLACKBOARD (post_to_layer_blackboard):
   → Coordination with agents EXECUTING IN THIS LAYER RIGHT NOW
   → Use for: "I'm building X, need Y from you", "Found blocker Z", "Done!"
   → This is where parallel agents discuss implementation details

2. YOUR NOTEBOOK (write_to_notebook, read_notebook):
   → Private to you, not visible to other agents
   → Use for: TODO list, decisions, detailed notes, assumptions
   → Start with write_to_notebook("TODO: item1, item2, item3", section="TODO")

3. DIRECT QUESTIONS (ask_agent, read_agent_messages, reply_agent_message):
    → MUST go through Service Bus for directed agent-to-agent questions
    → ask_agent() sends a direct message to another agent
    → read_agent_messages() checks incoming direct messages
    → reply_agent_message() is required for answering direct questions sent to you

═══════════════════════════════════════════════════════════════════════════════
PARALLEL COORDINATION (Lean & Practical)
═══════════════════════════════════════════════════════════════════════════════

If you're in a parallel layer:
• Post one concise plan on layer blackboard, then execute.
• Use files/workspace as primary truth; use messages for blockers or breaking changes.
• Before finishing: read latest layer blackboard + reply to pending direct questions.

═══════════════════════════════════════════════════════════════════════════════
CRITICAL NOTES
═══════════════════════════════════════════════════════════════════════════════

• LAYER BLACKBOARD: Use post_to_layer_blackboard(), not announce_plan()!
• PARALLEL AGENTS: Check task description for agent list
• Package Dependencies: Always list requirements (package.json, requirements.txt, etc)
• Documentation: Always create README.md in your workspace with setup + file overview
• Testing: QA Engineer writes tests. Everyone else writes code only.
• If blocked by a same-layer dependency, use sleep_agent() and resume only after wake_agent() signal
• Error Strategy: If same error 3x → it's external, work around it and continue
• Mocks are allowed only as clearly temporary fallbacks and must be documented
• Prefer concrete code/file changes over long coordination threads
• If unsure: Use sensible defaults and note assumptions in your notebook

═══════════════════════════════════════════════════════════════════════════════
YOUR SPECIFIC ROLE
═══════════════════════════════════════════════════════════════════════════════

{specific_instructions}

═══════════════════════════════════════════════════════════════════════════════
TERMINATION
═══════════════════════════════════════════════════════════════════════════════

When your task is COMPLETE:
    Output: [READY_FOR_VERIFICATION]
  
The orchestrator verifies deliverables before marking your task complete.
DO NOT ask "should I do X?" - just do it and finish with [READY_FOR_VERIFICATION].

BUILD FAST. COORDINATE ON LAYER BLACKBOARD. END WITH [READY_FOR_VERIFICATION]."""

    def __init__(self, role="General Developer", role_description="", specific_instructions="", 
                 allowed_root="./workspace", timeout=60, max_iterations=100):
        """
        Initialize the agent with role-specific configuration.
        
        Args:
            role: Role name (e.g., "Backend Engineer", "Frontend Developer")
            role_description: Description of what this role does
            specific_instructions: Role-specific instructions and requirements
            allowed_root: Root directory for file operations
            timeout: Command execution timeout in seconds
            max_iterations: Maximum iterations before giving up
        """
        self.role = role
        self.role_description = role_description
        self.specific_instructions = specific_instructions
        self.allowed_root = allowed_root
        self.timeout = timeout
        self.max_iterations = max_iterations
        
        # Initialize Azure OpenAI client
        self.client = AzureOpenAI(
            api_key=os.getenv("AZURE_OPENAI_KEY"),
            api_version="2024-05-01-preview",
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
        )
        
        # Initialize tools
        from tooly import ToolConfig
        tool_config = ToolConfig(allowed_root=allowed_root, timeout=timeout)
        base_tool_registry = ToolRegistry(tool_config)
        
        # Wrap in CWD-aware registry, pass workspace root
        workspace_root = os.path.dirname(allowed_root)
        self.tools_registry = CWDAwareToolRegistry(base_tool_registry, allowed_root, workspace_root)
        
        # Build system prompt using plain replacement (no .format), so brace escaping is unnecessary.
        self.system_prompt = self.GENERIC_SYSTEM_PROMPT.replace(
            "{role}", role
        ).replace(
            "{role_description}", role_description
        ).replace(
            "{specific_instructions}", specific_instructions
        )
    
    def get_tools(self):
        """Get tool definitions for the API"""
        return self.tools_registry.get_tool_definitions()

    def _log_ai_response(self, iteration: int, content: str, tool_calls=None):
        """Persist model outputs for debugging and auditability."""
        try:
            os.makedirs(AI_RESPONSES_LOG_DIR, exist_ok=True)
            safe_role = re.sub(r"[^a-zA-Z0-9_-]+", "_", (self.role or "agent").lower())
            ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
            out_path = os.path.join(AI_RESPONSES_LOG_DIR, f"{safe_role}_iter{iteration + 1}_{ts}.log")
            payload = {
                "timestamp": datetime.utcnow().isoformat(),
                "role": self.role,
                "iteration": iteration + 1,
                "chars": len(content or ""),
                "tool_call_count": len(tool_calls or []),
                "content": content or "",
                "tool_calls": [
                    {
                        "name": c.function.name,
                        "arguments": c.function.arguments,
                    }
                    for c in (tool_calls or [])
                ],
            }
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(json.dumps(payload, indent=2))
        except Exception:
            pass
    
    def execute(self, task_description, context=None):
        """
        Execute the agent for a given task.
        
        Args:
            task_description: What the agent should do
            context: Dict with upstream information (database schema, etc)
        
        Returns:
            Final message from agent (should contain completion summary)
        """
        print(f"\n[DEBUG] execute() called with task_description length: {len(task_description)}")
        
        if context is None:
            context = {}

        # Reset per-run sleep flag.
        if hasattr(self, "tools_registry"):
            self.tools_registry.sleep_requested = False
            self.tools_registry.read_operations = 0
            self.tools_registry.cross_workspace_reads = 0
            self.tools_registry.discovery_operations = 0
            self.tools_registry._last_discovery_signature = ""
            self.tools_registry._last_discovery_repeat_count = 0
            self.tools_registry.write_operations = 0
            self.tools_registry.file_write_counts = {}
            self.tools_registry.upstream_reads_before_first_write = 0
            self.tools_registry.validation_actions = 0

        is_fix_mode = "SECOND ITERATION - ISSUE FIX MODE" in (task_description or "")
        
        # CRITICAL FIX: Don't dump entire context (includes all upstream files)
        # Only send high-level summary. Agents can read files directly via read_file()
        context_summary = {
            "project_name": context.get("project_name", ""),
            "requirements": context.get("requirements", []),
            "tech_stack": context.get("tech_stack", {}),
            "required_upstream_roles": context.get("required_upstream_roles", []),
            "previous_outputs": {
                role: {
                    "workspace": info.get("workspace", ""),
                    "files": (info.get("files", []) or [])[:20]
                }
                for role, info in (context.get("previous_outputs", {}) or {}).items()
            },
            "note": "Use read_file() to inspect upstream agent workspaces if needed"
        }
        
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"Task: {task_description}\n\nContext: {json.dumps(context_summary)}"}
        ]

        # Local progress tracking (self-check before readiness token)
        successful_write_count = 0
        manifest_written = False
        readiness_rejections = 0
        unread_peer_rejections = 0
        missing_path_discovery_errors = 0
        manifest_candidates = ["package.json", "requirements.txt", "pyproject.toml"]
        manifest_exists_on_disk = any(
            os.path.exists(os.path.join(self.allowed_root, manifest))
            for manifest in manifest_candidates
        )

        def _has_existing_deliverables() -> bool:
            """Return True when workspace already has non-trivial files from prior iterations."""
            try:
                ignored_dirs = {".git", "node_modules", "dist", "build", "coverage", "__pycache__"}
                for root, dirs, files in os.walk(self.allowed_root):
                    dirs[:] = [d for d in dirs if d not in ignored_dirs]
                    for name in files:
                        if name.startswith("."):
                            continue
                        if name.endswith(".pyc"):
                            continue
                        return True
                return False
            except Exception:
                return False

        def _compact_messages_for_context(msgs, keep_recent: int):
            """Prune context using a contiguous suffix while preserving tool-call/tool-result protocol integrity."""
            if len(msgs) <= 2:
                return msgs

            head = msgs[:2]
            body = msgs[2:]
            if len(body) <= keep_recent:
                return msgs

            # Start with recent suffix, then expand backward if it contains tool
            # messages whose parent assistant tool_calls message is outside the window.
            start = max(0, len(body) - keep_recent)

            tool_id_to_assistant_index = {}
            for idx, m in enumerate(body):
                if m.get("role") == "assistant" and m.get("tool_calls"):
                    for tc in (m.get("tool_calls") or []):
                        tcid = (tc or {}).get("id")
                        if tcid:
                            tool_id_to_assistant_index[tcid] = idx

            changed = True
            while changed:
                changed = False
                for m in body[start:]:
                    if m.get("role") != "tool":
                        continue
                    tcid = m.get("tool_call_id")
                    parent_idx = tool_id_to_assistant_index.get(tcid)
                    if parent_idx is not None and parent_idx < start:
                        start = parent_idx
                        changed = True
                        break

            return head + body[start:]

        def _append_notebook_memory_snapshot(msgs):
            if not hasattr(self, "tools_registry"):
                return msgs
            notebooks_dir = getattr(self.tools_registry, "notebooks_dir", None)
            role_name = getattr(self.tools_registry, "agent_role", None) or os.path.basename(os.path.normpath(self.allowed_root))
            if not notebooks_dir or not role_name:
                return msgs
            notebook_path = os.path.join(notebooks_dir, f"{role_name}.md")
            if not os.path.exists(notebook_path):
                return msgs
            try:
                with open(notebook_path, "r", encoding="utf-8", errors="ignore") as f:
                    notebook_tail = f.read()[-2500:]
                if notebook_tail.strip():
                    msgs.append({
                        "role": "user",
                        "content": (
                            "Memory refresh: keep following your existing notebook plan and architecture notes. "
                            "Do not restart from scratch. Latest notebook excerpt:\n" + notebook_tail
                        )
                    })
            except Exception:
                pass
            return msgs
        
        # Main execution loop
        for iteration in range(self.max_iterations):
            # OPTIMIZATION: Aggressively prune context to avoid token limit
            # Estimate tokens (rough: 1 token ≈ 4 bytes)
            messages_str = json.dumps(messages)
            estimated_tokens = len(messages_str) / 4
            
            # Prune early to protect TPM across parallel agents.
            if estimated_tokens > CONTEXT_PRUNE_HARD_MAX_TOKENS:
                print(f"⚠️  CONTEXT WARNING: ~{int(estimated_tokens):,} tokens used, hard pruning...")
                messages = _compact_messages_for_context(messages, keep_recent=max(8, CONTEXT_PRUNE_HARD_KEEP_RECENT))
                messages = _append_notebook_memory_snapshot(messages)
            # Standard pruning if getting large
            elif estimated_tokens > CONTEXT_PRUNE_SOFT_MAX_TOKENS or len(messages) > CONTEXT_PRUNE_SOFT_MAX_MESSAGES:
                messages = _compact_messages_for_context(messages, keep_recent=max(20, CONTEXT_PRUNE_SOFT_KEEP_RECENT))
                messages = _append_notebook_memory_snapshot(messages)

            # Poll Service Bus inbox so agents are proactively notified.
            if hasattr(self, "tools_registry") and getattr(self.tools_registry, "service_bus", None) is not None:
                try:
                    bus = self.tools_registry.service_bus
                    if bus.is_enabled():
                        inbox = bus.receive_for_agent(
                            self.tools_registry.agent_role or os.path.basename(os.path.normpath(self.allowed_root)),
                            max_messages=10,
                            wait_seconds=0.5
                        )
                        if inbox:
                            lines = ["New Service Bus messages (you MUST respond to direct questions):"]
                            for m in inbox:
                                msg_id = m.get("id", "unknown")
                                msg_type = m.get("type", "unknown")
                                from_agent = m.get("from_agent", "unknown")
                                content = m.get("content", "")
                                lines.append(f"- [{msg_type}] {msg_id} from {from_agent}: {content}")
                                if msg_type == "question":
                                    self.tools_registry.pending_bus_questions[msg_id] = m

                            messages.append({"role": "user", "content": "\n".join(lines)})
                except Exception as e:
                    print(f"⚠️ Service Bus inbox polling failed: {e}")
                    messages.append({
                        "role": "user",
                        "content": (
                            "Service Bus inbox polling failed due to runtime error. "
                            f"Error: {str(e)}. Call read_agent_messages() now and proceed with replies if needed."
                        )
                    })

            pending_questions = list(getattr(self.tools_registry, "pending_bus_questions", {}).keys()) if hasattr(self, "tools_registry") else []
            if pending_questions:
                preview_ids = ", ".join(pending_questions[:5])
                messages.append({
                    "role": "user",
                    "content": (
                        "You have pending direct Service Bus questions that must be answered immediately. "
                        f"Pending message IDs: {preview_ids}. "
                        "Before any new planning/work, call reply_agent_message() for each pending question."
                    )
                })
            
            # Add a small delay between model calls to reduce bursty 429s
            delay = random.uniform(MODEL_CALL_DELAY_MIN, MODEL_CALL_DELAY_MAX)
            time.sleep(delay)

            # Call GPT-4o with tools
            response = self.client.chat.completions.create(
                model=AZURE_MODEL_DEPLOYMENT,
                messages=messages,
                tools=self.get_tools(),
                tool_choice="auto"
            )
            
            print(f"\n{'='*60}")
            print(f"Iteration {iteration + 1}:")
            print(f"{'='*60}")
            
            assistant_message = response.choices[0].message
            self._log_ai_response(iteration, assistant_message.content or "", assistant_message.tool_calls or [])
            
            # Convert ChatCompletionMessage to dict for JSON serialization
            # This is required for token estimation (json.dumps())
            message_dict = {
                "role": "assistant",
                "content": assistant_message.content if assistant_message.content else ""
            }
            
            # Include tool_calls in serializable form (Azure API requires this)
            # Convert ToolCall objects to dicts with function name and arguments
            if assistant_message.tool_calls:
                message_dict["tool_calls"] = [
                    {
                        "id": call.id,
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments  # Already a string
                        },
                        "type": "function"
                    }
                    for call in assistant_message.tool_calls
                ]
            
            messages.append(message_dict)
            
            # Print agent thought
            if assistant_message.content:
                thought = assistant_message.content[:300]
                print(f"🧠 Agent: {thought}")
                if len(assistant_message.content) > 300:
                    print("    ...")
                if AGENT_TRACE_MODE in {"code", "raw"}:
                    print("\n🧾 Full model output:")
                    print(assistant_message.content)
            
            # Check readiness token (Option B: explicit readiness token)
            content = assistant_message.content or ""
            has_ready_token = "[READY_FOR_VERIFICATION]" in content or "[DONE]" in content
            if has_ready_token:
                is_qa_role = ("qa" in self.role.lower() or "test" in self.role.lower())
                is_frontend_or_backend = ("frontend" in self.role.lower() or "backend" in self.role.lower())
                is_contract_only_role = ("api designer" in self.role.lower() or "api_designer" in self.role.lower())
                requires_parallel_sync = (
                    hasattr(self, "tools_registry")
                    and getattr(self.tools_registry, "layer_blackboard", None) is not None
                    and len(getattr(self.tools_registry, "parallel_peers", []) or []) > 0
                )
                if successful_write_count == 0:
                    if _has_existing_deliverables():
                        print("\n✅ Existing deliverables found on disk; accepting readiness without new writes in this run")
                    else:
                        print("\n⚠️ Readiness token received but no files were written in this run. Continuing...")
                        readiness_rejections += 1
                        messages.append({
                            "role": "user",
                            "content": (
                                "Readiness rejected: no deliverable files were written yet. "
                                "Create required files with write_file(), then output [READY_FOR_VERIFICATION]."
                            )
                        })
                elif not manifest_written and not is_qa_role and not is_contract_only_role:
                    # Accept existing manifest if it already exists on disk
                    manifest_exists_on_disk = any(
                        os.path.exists(os.path.join(self.allowed_root, manifest))
                        for manifest in manifest_candidates
                    )
                    if manifest_exists_on_disk:
                        print("\n✅ Existing dependency manifest found on disk; accepting readiness")
                        return "[READY_FOR_VERIFICATION]"

                    print("\n⚠️ Readiness token received but no dependency manifest written. Continuing...")
                    readiness_rejections += 1
                    messages.append({
                        "role": "user",
                        "content": (
                            "Readiness rejected: missing dependency manifest. "
                            "Create one now (package.json or requirements.txt or pyproject.toml), "
                            "then output [READY_FOR_VERIFICATION]."
                        )
                    })
                elif not is_fix_mode and hasattr(self, "tools_registry") and (not self.tools_registry.plan_announced or not self.tools_registry.todo_noted):
                    print("\n⚠️ Readiness token received but planning artifacts are incomplete. Continuing...")
                    readiness_rejections += 1
                    messages.append({
                        "role": "user",
                        "content": (
                            "Readiness rejected: planning discipline is incomplete. "
                            "You must announce_plan() and write_to_notebook() with a TODO list before completion. "
                            "Then continue implementation and output [READY_FOR_VERIFICATION]."
                        )
                    })
                elif not is_fix_mode and is_frontend_or_backend and hasattr(self, "tools_registry") and not self.tools_registry.design_noted:
                    print("\n⚠️ Readiness token received but no architecture/flow notes were recorded. Continuing...")
                    readiness_rejections += 1
                    messages.append({
                        "role": "user",
                        "content": (
                            "Readiness rejected: for frontend/backend quality, record your intended structure and flow first. "
                            "Use write_to_notebook(section='ARCHITECTURE') to document directory/component/route flow, "
                            "then continue implementation and output [READY_FOR_VERIFICATION]."
                        )
                    })
                elif not is_fix_mode and is_frontend_or_backend and hasattr(self, "tools_registry") and self.tools_registry.validation_actions <= 0:
                    print("\n⚠️ Readiness token received but no validation checks were run. Continuing...")
                    readiness_rejections += 1
                    messages.append({
                        "role": "user",
                        "content": (
                            "Readiness rejected: run at least one targeted validation step with run_command() or check_syntax() "
                            "for touched integration paths, then output [READY_FOR_VERIFICATION]."
                        )
                    })
                elif requires_parallel_sync:
                    total_peer_messages = 0
                    if hasattr(self.tools_registry.layer_blackboard, "peer_message_count"):
                        total_peer_messages = self.tools_registry.layer_blackboard.peer_message_count(self.tools_registry.agent_role)
                    read_count = getattr(self.tools_registry, "layer_blackboard_read_count", 0)
                    seen_peer_count = getattr(self.tools_registry, "layer_blackboard_last_seen_peer_count", 0)
                    post_count = getattr(self.tools_registry, "layer_blackboard_post_count", 0)
                    post_after_read = bool(getattr(self.tools_registry, "layer_blackboard_post_after_read", False))
                    if read_count == 0:
                        print("\n⚠️ Readiness token received but layer blackboard was never read. Continuing...")
                        readiness_rejections += 1
                        messages.append({
                            "role": "user",
                            "content": (
                                "Readiness rejected: you must call read_layer_blackboard() and acknowledge peer updates "
                                "before finishing in parallel execution. Then output [READY_FOR_VERIFICATION]."
                            )
                        })
                    elif total_peer_messages > seen_peer_count:
                        unread_gap = total_peer_messages - seen_peer_count
                        pending_questions = list(getattr(self.tools_registry, "pending_bus_questions", {}).keys())
                        if unread_peer_rejections >= 1 and unread_gap <= 2 and not pending_questions:
                            print("\n✅ Minor unread peer delta remains; accepting readiness to prevent coordination deadlock")
                            return "[READY_FOR_VERIFICATION]"

                        print("\n⚠️ Readiness token received but there are unread peer updates on layer blackboard. Continuing...")
                        unread_peer_rejections += 1
                        readiness_rejections += 1
                        messages.append({
                            "role": "user",
                            "content": (
                                "Readiness rejected: new peer layer-blackboard messages were posted after your last read. "
                                "Call read_layer_blackboard() again, address updates, then output [READY_FOR_VERIFICATION]."
                            )
                        })
                    elif post_count < 1:
                        print("\n⚠️ Readiness token received but team discussion on blackboard is insufficient. Continuing...")
                        readiness_rejections += 1
                        messages.append({
                            "role": "user",
                            "content": (
                                "Readiness rejected: in parallel execution, act as a team on the layer blackboard. "
                                "Post at least one concise layer-blackboard update about your plan or changes. "
                                "After that, output [READY_FOR_VERIFICATION]."
                            )
                        })
                    else:
                        pending_questions = list(getattr(self.tools_registry, "pending_bus_questions", {}).keys())
                        if pending_questions:
                            print("\n⚠️ Readiness token received but unanswered Service Bus questions remain. Continuing...")
                            readiness_rejections += 1
                            messages.append({
                                "role": "user",
                                "content": (
                                    "Readiness rejected: you have unanswered direct Service Bus questions. "
                                    "Call read_agent_messages(), then reply_agent_message() for each question, "
                                    "and only then output [READY_FOR_VERIFICATION]."
                                )
                            })
                        else:
                            print("\n✅ Agent marked ready for external verification")
                            return "[READY_FOR_VERIFICATION]"
                else:
                    has_upstream = bool((context.get("previous_outputs") or {}))
                    required_upstream = list(context.get("required_upstream_roles", []) or [])
                    if has_upstream and required_upstream and getattr(self.tools_registry, "cross_workspace_reads", 0) <= 0:
                        print("\n⚠️ Readiness token received but no upstream files were inspected. Continuing...")
                        readiness_rejections += 1
                        messages.append({
                            "role": "user",
                            "content": (
                                "Readiness rejected: you must inspect relevant upstream code before completion. "
                                f"Required upstream roles: {', '.join(required_upstream)}. "
                                "Use list_files/search_in_files/read_file, then resume implementation and output [READY_FOR_VERIFICATION]."
                            )
                        })
                        continue

                    if has_upstream and required_upstream and not is_fix_mode and getattr(self.tools_registry, "upstream_reads_before_first_write", 0) <= 0:
                        print("\n⚠️ Readiness token received but upstream inspection happened too late or not at all. Continuing...")
                        readiness_rejections += 1
                        messages.append({
                            "role": "user",
                            "content": (
                                "Readiness rejected: inspect upstream contracts before writing deliverables. "
                                "Perform cross-workspace list/search/read first, then continue implementation and output [READY_FOR_VERIFICATION]."
                            )
                        })
                        continue

                    pending_questions = list(getattr(self.tools_registry, "pending_bus_questions", {}).keys())
                    if pending_questions:
                        print("\n⚠️ Readiness token received but unanswered Service Bus questions remain. Continuing...")
                        readiness_rejections += 1
                        messages.append({
                            "role": "user",
                            "content": (
                                "Readiness rejected: you have unanswered direct Service Bus questions. "
                                "Call read_agent_messages(), then reply_agent_message() for each question, "
                                "and only then output [READY_FOR_VERIFICATION]."
                            )
                        })
                    else:
                        print("\n✅ Agent marked ready for external verification")
                        return "[READY_FOR_VERIFICATION]"

                # Safety valve to avoid silent stalls
                if readiness_rejections >= 3:
                    print("\n⚠️ Repeated readiness rejections. Returning control for orchestrator remediation.")
                    return "NOT_READY_FOR_VERIFICATION"
            
            # Execute tool calls
            if assistant_message.tool_calls:
                for tool_call in assistant_message.tool_calls:
                    function_name = tool_call.function.name
                    
                    try:
                        function_args = json.loads(tool_call.function.arguments)
                    except:
                        result = "ERROR: Invalid JSON arguments"
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": result
                        })
                        continue
                    
                    # Execute the tool
                    print(f"🔧 Tool: {function_name}({json.dumps(function_args)[:100]})")
                    result = self.tools_registry.execute_tool(function_name, function_args)
                    
                    # CONTEXT PROTECTION: Truncate very large tool results
                    # Command output or file listings can be huge (e.g., jest output, npm install)
                    # Limit to 10KB per result to prevent context explosion
                    MAX_RESULT_SIZE = 10000
                    if len(result) > MAX_RESULT_SIZE:
                        result = result[:MAX_RESULT_SIZE] + f"\n\n... [OUTPUT TRUNCATED - Original size: {len(result)} bytes] ..."
                    
                    # Print result (truncated)
                    result_preview = result[:500]
                    if len(result) > 500:
                        result_preview += "\n    ..."
                    print(f"📤 Result:\n    {result_preview}")
                    
                    # Alert on command failures
                    if function_name == "run_command" and has_command_failed(result):
                        print("    ⚠️  WARNING: Command failed! Check exit code and error messages.")

                    if function_name in {"read_file", "list_files", "search_files", "search_in_files"}:
                        if (
                            isinstance(result, str)
                            and (
                                result.startswith("ERROR: Directory not found:")
                                or result.startswith("ERROR: File not found:")
                            )
                        ):
                            missing_path_discovery_errors += 1
                        elif isinstance(result, str) and result.startswith("✅"):
                            # Decay on successful discovery to avoid stale false positives.
                            missing_path_discovery_errors = max(0, missing_path_discovery_errors - 1)

                        if missing_path_discovery_errors >= 12:
                            print("\n⚠️ Circuit breaker: repeated missing-path discovery failures detected.")
                            print("    Returning control to orchestrator for remediation.")
                            return "NOT_READY_FOR_VERIFICATION"

                    # Track successful file writes + manifest creation
                    if function_name == "write_file" and "Successfully wrote to" in result:
                        successful_write_count += 1
                        written_path = (function_args.get("file_path", "") or "").lower()
                        if written_path.endswith("package.json") or written_path.endswith("requirements.txt") or written_path.endswith("pyproject.toml"):
                            manifest_written = True

                    if function_name == "sleep_agent" and str(result).startswith("✅ Sleep requested"):
                        print("    ⏸️ Sleep requested by agent")
                        return "[SLEEP_REQUESTED]"
                    
                    # Send tool result back
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result
                    })
            else:
                # No tool calls: continue unless explicit readiness token handled above
                if iteration > 2:
                    print(f"⚠️ Agent thinking without taking action (iteration {iteration + 1})")
                    print(f"    Hint: build deliverables, write manifest, then output [READY_FOR_VERIFICATION]")
                    messages.append({
                        "role": "user",
                        "content": (
                            "You did not call any tools or output [READY_FOR_VERIFICATION]. "
                            "You MUST take one concrete action now: call a tool to create/fix/read files, "
                            "or output [READY_FOR_VERIFICATION] only if all requirements are truly complete."
                        )
                    })
                else:
                    print(f"💭 Agent planning... continuing")
                continue
        
        print(f"\n⚠️ Agent hit max iterations ({self.max_iterations})")
        return "Agent did not complete in time"


# Pre-configured agent roles
class BackendEngineerAgent(GeneralAgent):
    """Backend Engineer Agent - for API/server development"""
    
    def __init__(self, allowed_root="./workspace", timeout=60):
        super().__init__(
            role="Backend Engineer",
            role_description=(
                "Develop server-side logic, APIs, database access, and business logic. "
                "You implement controllers, routes, models, and integrate with upstream architecture."
            ),
            specific_instructions="""
═══════════════════════════════════════════════════════════════════════════════
BACKEND ENGINEER WORKFLOW - GENERIC API DEVELOPMENT
═══════════════════════════════════════════════════════════════════════════════

API CONTRACT COMPLIANCE (MANDATORY):
    ✅ Read contracts/api_contract.json before implementation
    ✅ Implement endpoints, field names, request/response JSON shapes, and status codes EXACTLY as defined
    ✅ Do NOT invent routes, payload fields, or response formats
    ✅ If contract is missing/ambiguous, stop guessing and request clarification via blackboard

PHASE 1: ANALYZE REQUIREMENTS (Iteration 1-2)
  ├─ read_file("../database_architect/migrations/schema.sql") - Understand data model
  ├─ read_file("../security_engineer/middleware/authMiddleware.js") - Know auth pattern
  ├─ Identify all backend requirements (endpoints, operations, flows)
  └─ Announce backend plan to blackboard

PHASE 2: BUILD CORE LAYER
  Priority 1 - CRITICAL (Files 1-5):
    ├─ config/database.js - Database connection pool
    ├─ models/base.js - Base model class/utilities
    ├─ models/*.js - Data models matching upstream schema
    └─ controllers/* - Endpoint handlers for critical operations

  Priority 2 - CRITICAL OPERATIONS (Files 6-10):
    ├─ routes/*.js - API route definitions
    ├─ middleware/auth.js - Authentication/authorization
    ├─ middleware/validation.js - Input validation
    ├─ utils/helpers.js - Business logic utilities
    └─ app.js - Main Express server

  Priority 3 - IMPORTANT (Files 11-15):
    ├─ middleware/errorHandler.js - Error handling
    ├─ middleware/logger.js - Request logging (optional)
    ├─ config/.env - Environment configuration
    └─ tests/unit.test.js - Unit tests

  Priority 4 - NICE-TO-HAVE (File 16+):
    ├─ tests/integration.test.js - Integration tests
    ├─ utils/validation.js - Complex validators
    └─ package.json - Dependencies

    IMPORTANT: ALWAYS, ALWAYS WRITE FULL CODE. NEVER WRITE PLACEHOLDER LOGIC IN ANY SCENARIO. YOUR FINAL OUTPUT MUT BE WORKING.
    TRY TO DO AS MUCH AS POSSIBLE IN ONE ITERATION.

PHASE 3: IMPLEMENT CRITICAL OPERATIONS
  ✅ Core CRUD operations: Create, Read, Update, Delete for main entities
  ✅ Business logic: Complex operations involving multiple tables/validations
  ✅ Authentication: Verify tokens, manage user sessions
  ✅ Error handling: Proper HTTP codes and error messages
  ✅ Validation: Input validation on all endpoints
  ✅ Database integration: Connection pooling, prepared statements

PHASE 4: INTEGRATION
  ├─ Verify endpoints match database schema
  ├─ Verify middleware chains are correct
  ├─ Verify error handling works
    ├─ Add centralized error middleware + request logging middleware
    ├─ Add health/readiness endpoint(s) for runtime checks
    ├─ Wrap unstable dependency calls with bounded retry/backoff where appropriate
  ├─ Run: npm install && npm test
  └─ Document any external dependencies

PHASE 5: TESTING (Final)
  ├─ If database available: Run full test suite
  ├─ If database NOT available: Create test stubs with mocks
  ├─ Do NOT spend 10+ iterations fixing external service issues
  └─ Update_blackboard with test status

PRODUCTION READINESS (MANDATORY):
    ✅ Defensive try/catch on all controller entry points
    ✅ No unhandled promise rejections in request paths
    ✅ Structured logging on request/error paths (route + status + error code)
    ✅ Stable API error envelope for frontend consumers
    ✅ Timeouts and retry policy for flaky external dependencies

═══════════════════════════════════════════════════════════════════════════════
BACKEND PATTERNS - FOLLOW THESE
═══════════════════════════════════════════════════════════════════════════════

Database Connection:
  const pool = new Pool({
    user: process.env.DB_USER,
    password: process.env.DB_PASSWORD,
    host: process.env.DB_HOST,
    port: process.env.DB_PORT,
    database: process.env.DB_NAME
  });

Data Model:
  class EntityModel {
    async getById(id) {
      const query = 'SELECT * FROM entity WHERE id = $1';
      const result = await pool.query(query, [id]);
      return result.rows[0];
    }
    
    async create(data) {
      const query = 'INSERT INTO entity (field1, field2) VALUES ($1, $2) RETURNING *';
      const result = await pool.query(query, [data.field1, data.field2]);
      return result.rows[0];
    }
  }

Controller:
  exports.getEntity = async (req, res) => {
    try {
      const id = req.params.id;
      const entity = await model.getById(id);
      if (!entity) return res.status(404).json({ error: 'Not found' });
      res.json(entity);
    } catch (error) {
      console.error(error);
      res.status(500).json({{ error: 'Server error' }});
    }
  };

Route Definition:
  router.get('/entities/:id', authMiddleware, entityController.getEntity);

═══════════════════════════════════════════════════════════════════════════════
HANDLING MISSING DEPENDENCIES
═══════════════════════════════════════════════════════════════════════════════

Database not available?
  ✅ Write models with real query logic
  ✅ Tests will fail but code is correct
  ✅ Document: "Requires PostgreSQL 12+. Connection string in .env"

Upstream schema missing?
    ❌ Do NOT use defaults
    ✅ STOP and report a blocking issue referencing contracts/api_contract.json

Auth service not ready?
    ✅ Implement contract-defined auth boundary only
    ❌ Do NOT fake token verification semantics

External API unavailable?
    ✅ Return explicit dependency failure where appropriate
    ❌ Do NOT add mock response paths that hide contract behavior

═══════════════════════════════════════════════════════════════════════════════
OUTPUT FILES (relative paths in your workspace)
═══════════════════════════════════════════════════════════════════════════════

config/
  ├─ database.js - Database connection pool
  └─ .env - Environment variables (credentials)

models/
  ├─ base.js - Base model class/utilities
  └─ *.js - Data models (user.js, product.js, order.js, etc)

controllers/
  └─ *.js - Request handlers for each resource

routes/
  └─ *.js - API route definitions

middleware/
  ├─ auth.js - Authentication/authorization verification
  ├─ validation.js - Input validation
  └─ errorHandler.js - Error handling

utils/
  ├─ helpers.js - Business logic utilities
  └─ constants.js - Constants/enums

tests/
  ├─ unit.test.js - Unit tests for models/logic
  └─ integration.test.js - Integration tests

Root level:
  ├─ app.js - Main Express server
  └─ package.json - Dependencies

═══════════════════════════════════════════════════════════════════════════════
SUCCESS CRITERIA FOR YOUR DELIVERABLES
═══════════════════════════════════════════════════════════════════════════════

✅ All critical endpoints created (CRUD + business logic)
✅ Writing as much code as possible in lesser iterations
✅ Database models matching upstream schema
✅ Authentication middleware working
✅ Input validation on all endpoints
✅ Proper error handling and HTTP status codes
✅ Async/await (no callback hell)
✅ No hardcoded secrets (uses environment variables)
✅ Code is well-structured and maintainable
✅ Tests created (even if they fail due to external deps)

═══════════════════════════════════════════════════════════════════════════════
IF REQUIREMENTS UNCLEAR - ESCALATE, DO NOT GUESS
═══════════════════════════════════════════════════════════════════════════════

❓ Any endpoint ambiguity? → STOP and request contract clarification
❓ Any field mismatch? → STOP and align with contracts/api_contract.json
❓ Any response uncertainty? → STOP and report exact blocking section
❓ Any schema uncertainty? → STOP and request database/api alignment

NEVER: "I can't implement backend without X"
INSTEAD: "Blocked by missing/ambiguous contract detail; clarification requested"
""",
            allowed_root=allowed_root,
            timeout=timeout
        )


class FrontendDeveloperAgent(GeneralAgent):
    """Frontend Developer Agent - for UI development"""
    
    def __init__(self, allowed_root="./workspace", timeout=60):
        super().__init__(
            role="Frontend Developer",
            role_description=(
                "Build responsive, accessible user interfaces using modern frameworks. "
                "You handle component design, state management, and user interactions."
            ),
            specific_instructions="""
═══════════════════════════════════════════════════════════════════════════════
FRONTEND DEVELOPER WORKFLOW - GENERIC UI DEVELOPMENT
═══════════════════════════════════════════════════════════════════════════════

API CONTRACT COMPLIANCE (MANDATORY):
    ✅ Read contracts/api_contract.json before wiring API calls
    ✅ Use EXACT endpoint paths, params, field names, and response shapes from contract
    ✅ Do NOT invent frontend-only API fields or route variants
    ✅ If contract is missing/ambiguous, stop guessing and raise alignment note on blackboard

REACT FILE CONVENTION (MANDATORY):
    ✅ Use .jsx for React components/pages/app entry files
    ✅ Required entry files: src/main.jsx and src/App.jsx (or justify equivalent in README)
    ✅ Do NOT ship React UI only as .js component files

QUALITY GOAL (MANDATORY):
    ✅ Ship a HIGH-QUALITY frontend (not merely functional)
    ✅ Visual polish, strong spacing/typography hierarchy, responsive behavior
    ✅ Accessibility-first interactions and clear user feedback states

DESIGN SYSTEM + THEME (MANDATORY):
    ✅ Use Tailwind CSS as the default styling system
    ✅ Maintain a consistent design language (spacing scale, typography scale, color tokens)
    ✅ Implement Dark Mode support (class-based `dark` theme or equivalent token switch)
    ✅ Avoid scattered inline styles except tiny dynamic one-offs

BACKEND CONNECTIVITY CONTRACT (MANDATORY):
    ✅ Never hardcode backend host/port in components
    ✅ All API calls must resolve from env config first (REACT_APP_API_URL)
    ✅ Implement one API base resolver in src/utils/api.js and reuse everywhere
    ✅ Add .env.example documenting REACT_APP_API_URL (+ local default behavior)

PHASE 1: ANALYZE REQUIREMENTS (Iteration 1-2)
  ├─ read_file("../database_architect/migrations/schema.sql") - Understand data structures
  ├─ read_file("../backend_engineer/routes/*.js") - Know available API endpoints
  ├─ Identify all pages and components needed
  └─ Announce frontend plan to blackboard

PHASE 2: BUILD CORE PAGES
  Priority 1 - CRITICAL PAGES (Files 1-5):
        ├─ src/pages/HomePage.jsx or similar - Main/listing page
        ├─ src/pages/DetailPage.jsx or similar - Detail/form page
        ├─ src/components/Header.jsx or Navigation - Top-level navigation
        ├─ src/components/Footer.jsx - Common footer (if needed)
        └─ src/App.jsx - Main app component with routing

  Priority 2 - CRITICAL COMPONENTS
        ├─ src/components/*.jsx - Reusable UI components (cards, forms, etc)
    ├─ src/utils/api.js - API call utilities
        ├─ src/context/ or src/hooks/ - State management (if using Context/Redux)
        ├─ src/pages/*.jsx - Additional pages for main flows
    └─ src/styles/ - Styling (CSS, SCSS, or CSS-in-JS)

  Priority 3 - IMPORTANT
    ├─ src/App.css or src/styles/index.css - Global styles
        ├─ src/main.jsx - React entry point
    ├─ public/index.html - HTML template
        └─ tests/App.test.jsx - Component tests

  Priority 4 - NICE-TO-HAVE
    ├─ src/utils/helpers.js - Utility functions
    ├─ tests/components.test.js - Component tests
    ├─ .env.local - Frontend configuration
    └─ package.json - Dependencies

    IMPORTANT: ALWAYS, ALWAYS WRITE FULL CODE. NEVER WRITE PLACEHOLDER LOGIC IN ANY SCENARIO. YOUR FINAL OUTPUT MUT BE WORKING.
    TRY TO DO AS MUCH AS POSSIBLE IN ONE ITERATION.

PHASE 3: IMPLEMENT CRITICAL UI
  ✅ All main pages created (list, detail, form, etc)
  ✅ Navigation between pages works
  ✅ API integration for data fetching
  ✅ State management (Context API or simple useState)
  ✅ Error handling and loading states
  ✅ Basic responsive design (mobile-friendly)
  ✅ Accessible components (semantic HTML, ARIA labels)

PHASE 4: INTEGRATION
  ├─ Verify all pages render without errors
  ├─ Verify API calls work (or have fallback mocks)
  ├─ Verify navigation works between pages
  ├─ Test on mobile viewport
  └─ Run: npm install && npm start

PHASE 5: REFINEMENT (Final)
  ├─ Fix console errors and warnings
  ├─ Improve styling and UX
  ├─ Add tests if time available
  └─ Do NOT spend 10+ iterations on CSS polish

═══════════════════════════════════════════════════════════════════════════════
UI PATTERNS - FOLLOW THESE
═══════════════════════════════════════════════════════════════════════════════

Functional Component with Hooks:
  function PageName() {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    useEffect(() => {
      setLoading(true);
      fetchData()
        .then(setData)
        .catch(setError)
        .finally(() => setLoading(false));
    }, []);

    if (loading) return <div>Loading...</div>;
    if (error) return <div>Error: {error.message}</div>;
    return <div>{{/* render data */}}</div>;
  }

State Management with Context:
  const DataContext = React.createContext();
  
  function DataProvider({ children }) {
    const [state, dispatch] = useReducer(reducer, initialState);
    return (
      <DataContext.Provider value={{ state, dispatch }}>
        {children}
      </DataContext.Provider>
    );
  }

API Utilities:
    const BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:5000';

  export const api = {
        getList: () => fetch(`${BASE_URL}/api/items`).then(r => r.json()),
        getDetail: (id) => fetch(`${BASE_URL}/api/items/${id}`).then(r => r.json()),
        create: (data) => fetch(`${BASE_URL}/api/items`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    }).then(r => r.json())
  };

═══════════════════════════════════════════════════════════════════════════════
HANDLING BACKEND NOT READY
═══════════════════════════════════════════════════════════════════════════════

API endpoint doesn't exist yet?
    ❌ Do NOT invent or mock non-contract endpoints
    ✅ Raise a contract/backend mismatch issue with exact endpoint

Data structure unclear?
    ❌ Do NOT use defaults
    ✅ Read contract and block on ambiguity

Styling library missing?
  ✅ Use inline styles or basic CSS
  ✅ Don't wait for design system

Cannot connect to backend?
    ✅ Keep UI structure work independent of transport
    ❌ Do NOT fake contract responses as if integration is complete
    ✅ Mark integration as blocked until real backend path works

═══════════════════════════════════════════════════════════════════════════════
OUTPUT FILES (relative paths in your workspace)
═══════════════════════════════════════════════════════════════════════════════

src/
  ├─ pages/
    │  ├─ HomePage.jsx or List.jsx - Main listing page
    │  ├─ DetailPage.jsx or Form.jsx - Detail/form page
    │  └─ *.jsx - Other pages (search, results, etc)
  ├─ components/
    │  ├─ Header.jsx or Navigation.jsx - Top navigation
    │  ├─ Footer.jsx - Footer (optional)
    │  ├─ Card.jsx or ItemCard.jsx - Reusable card component
    │  ├─ Form.jsx or Input.jsx - Reusable form component
    │  └─ *.jsx - Other reusable components
  ├─ context/ or hooks/
  │  └─ *.js - State management (Context, Redux, or custom hooks)
  ├─ utils/
  │  ├─ api.js - API call utilities
  │  └─ helpers.js - Utility functions
  ├─ styles/
  │  ├─ index.css - Global styles
  │  └─ components.css - Component styles (optional)
    ├─ App.jsx - Main app component with routing
    ├─ main.jsx - React entry point
  └─ constants.js - Constants (API URLs, enums, etc)

public/
  ├─ index.html - HTML template
  └─ favicon.ico - Page icon

Root level:
  ├─ package.json - Dependencies
    ├─ .env.example - Environment variable template (REACT_APP_API_URL)
  ├─ .env.local - Environment variables
  └─ .gitignore - Git ignore rules

tests/
    ├─ App.test.jsx - App component tests
    └─ components.test.jsx - Component tests (optional)

═══════════════════════════════════════════════════════════════════════════════
SUCCESS CRITERIA FOR YOUR DELIVERABLES
═══════════════════════════════════════════════════════════════════════════════

✅ All critical pages created and render without errors
✅ Navigation between pages works
✅ Components are well-structured and reusable
✅ API integration (or mocks if backend not ready)
✅ State management working (simple or advanced)
✅ Error handling and loading states
✅ Mobile-responsive design
✅ Accessible markup (semantic HTML, ARIA where needed)
✅ Code is clean and maintainable
✅ Visual quality is production-grade (not bare/unstyled defaults)
✅ Styling is coherent through a Tailwind-based design system
✅ API base URL is env-driven (REACT_APP_API_URL), not hardcoded in feature components

═══════════════════════════════════════════════════════════════════════════════
IF REQUIREMENTS UNCLEAR - USE THESE PATTERNS
═══════════════════════════════════════════════════════════════════════════════

❓ What pages needed? → One for each major user flow (list, create, edit, detail)
❓ What state manager? → Start with useState/useContext, add Redux if too complex
❓ How to style? → CSS, Tailwind, Material-UI, or Styled Components (pick one)
❓ How to call API? → fetch() or axios, with error boundaries
❓ How to route? → React Router (most common choice)

NEVER: "I can't build frontend without X"
INSTEAD: "X not available, mocking it and building UI anyway"

DO:
  ✅ Create all pages
  ✅ Try to create as much as possible in a single iteration
  ✅ Make pages accessible
  ✅ Test on mobile
  ✅ Use hooks (useState, useEffect, useContext)
  ✅ Mock backend if needed
  ✅ Keep styling simple

DON'T:
  ❌ Skip creating pages
  ❌ Spend hours on CSS animations
  ❌ Use class components (use hooks instead)
  ❌ Mix state management approaches
  ❌ Create huge monolithic files (split into components)
  ❌ Write placeholder code/logic
""",
            allowed_root=allowed_root,
            timeout=timeout
        )


class DevOpsEngineerAgent(GeneralAgent):
    """DevOps Engineer Agent - for infrastructure and deployment"""
    
    def __init__(self, allowed_root="./workspace", timeout=60):
        super().__init__(
            role="DevOps Engineer",
            role_description=(
                "Setup and manage infrastructure, CI/CD pipelines, containerization, and deployment. "
                "You handle system configuration, monitoring, and operational excellence."
            ),
            specific_instructions="""
⚠️ DEVOPS ENGINEER SPECIFIC WORKFLOW (AZURE CONTAINER APPS FOCUSED):
1. Build deployment around Docker + Azure Container Apps
2. Create production-ready multi-stage Dockerfile(s)
3. Optimize image size/startup (small base image, prune dev deps, cache-friendly layers)
4. Define runtime env/secret contract (no hardcoded credentials)
5. Add health probe compatibility and startup command validation
6. Provide simple ACA deployment script/commands and rollback notes
7. Validate local container run before cloud deploy

OUTPUT FILES (all paths relative to your workspace root):
- Dockerfile (multi-stage)
- .dockerignore
- docker-compose.yml (optional for local integration)
- infrastructure.yaml or aca-deploy.sh (Azure Container Apps deployment)
- README.md (deploy, rollback, env setup, troubleshooting)

ALWAYS IMPLEMENT:
- Multi-stage Docker builds
- Runtime config through environment variables and secret references
- Health checks/probes wired to the app
- Minimal image footprint and predictable startup time
- Clear stdout/stderr logging for platform diagnostics

DO NOT:
- Generate Kubernetes/Terraform unless explicitly requested
- Hardcode Azure URLs/keys/secrets
- Ship heavyweight single-stage images when multi-stage is feasible
- Add unnecessary infra complexity for current target environment
""",
            allowed_root=allowed_root,
            timeout=timeout
        )


def main():
    """Example usage of the agent framework"""
    
    # Example: Create a backend engineer for a specific task
    agent = BackendEngineerAgent()
    
    result = agent.execute(
        task_description="Create a RESTFUL API for a bakery website with full CRUD functionality.",
        context={
            "database": "sqlite",
            "auth_method": "JWT",
        }
    )
    
    print("\n" + "="*60)
    print("FINAL RESULT:")
    print("="*60)
    print(result)


if __name__ == "__main__":
    main()
