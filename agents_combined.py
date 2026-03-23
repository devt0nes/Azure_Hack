from __future__ import annotations
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


import datetime
from enum import Enum
from typing import Dict, List, Tuple
import uuid
import time
import random

from openai import AzureOpenAI
import json
import os
from dotenv import load_dotenv
from tooly import ToolRegistry, has_command_failed, is_done

load_dotenv()

AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_MODEL_DEPLOYMENT = os.getenv("AZURE_MODEL_DEPLOYMENT")
MODEL_CALL_DELAY_MIN = float(os.getenv("MODEL_CALL_DELAY_MIN", "1.0"))
MODEL_CALL_DELAY_MAX = float(os.getenv("MODEL_CALL_DELAY_MAX", "2.0"))

# Workspace configuration
WORKSPACE_DIR = "./workspace"
os.makedirs(WORKSPACE_DIR, exist_ok=True)

class AgentRole(str, Enum):
    """Enumeration of available agent specializations."""
    BACKEND_ENGINEER = "backend_engineer"
    FRONTEND_ENGINEER = "frontend_engineer"
    DATABASE_ARCHITECT = "database_architect"
    DEVOPS_ENGINEER = "devops_engineer"
    SECURITY_ENGINEER = "security_engineer"
    QA_ENGINEER = "qa_engineer"
    SOLUTION_ARCHITECT = "solution_architect"
    API_DESIGNER = "api_designer"
    ML_ENGINEER = "ml_engineer"

def deep_update(original, new):
    """Safely merge nested dictionaries.

    Rules:
    - Recurse only when both sides are dicts
    - Replace on type mismatch (dict vs list, etc.)
    - Ignore non-dict updates to avoid runtime crashes
    """
    if not isinstance(original, dict) or not isinstance(new, dict):
        return

    for k, v in new.items():
        if isinstance(v, dict) and isinstance(original.get(k), dict):
            deep_update(original[k], v)
        else:
            original[k] = v


def _extract_role(agent_entry) -> str:
    """Extract role name from either string or dict agent entries."""
    if isinstance(agent_entry, str):
        return agent_entry
    if isinstance(agent_entry, dict):
        return agent_entry.get("agent_name") or agent_entry.get("role") or ""
    return ""


def _throttle_model_call():
    """Small delay between model calls to reduce bursty rate-limit errors."""
    time.sleep(random.uniform(MODEL_CALL_DELAY_MIN, MODEL_CALL_DELAY_MAX))


def _infer_agent_phase(agent: Dict) -> int:
    """Infer execution phase from role semantics (common-sense, keyword-based).

    Phase ordering:
    0 = foundations (architecture/data/security/api design)
    1 = core implementation (backend/ml)
    2 = integration/operations (devops/integration/deployment)
    3 = frontend assembly (typically after backend contracts stabilize)
    4 = validation/release (qa/testing/review)
    """
    role_name = str(agent.get("role", "")).lower()
    text = " ".join([
        str(agent.get("role", "")),
        str(agent.get("description", "")),
        str(agent.get("instructions", "")),
    ]).lower()

    validation_keywords = ["qa", "test", "testing", "validation", "verify", "review", "audit"]
    if any(k in text for k in validation_keywords):
        return 4

    # Frontend typically follows backend/API stabilization and is finalized later.
    if "frontend" in role_name or "ui" in role_name:
        return 3

    foundation_keywords = [
        "database", "data", "schema", "migration", "architect", "security", "api design", "api_designer"
    ]
    if any(k in text for k in foundation_keywords):
        return 0

    ops_keywords = ["devops", "deployment", "infra", "infrastructure", "integration", "ci/cd", "pipeline"]
    if any(k in text for k in ops_keywords):
        return 2

    impl_keywords = ["backend", "frontend", "fullstack", "full-stack", "ml", "engineer"]
    if any(k in text for k in impl_keywords):
        return 1

    # Unknown roles default to core implementation phase
    return 1


def default_workspace_layout() -> Dict:
    """Default production-like workspace layout used when model output is incomplete."""
    return {
        "directories": [
            "backend",
            "frontend",
            "database",
            "security",
            "devops",
            "infra",
            "scripts",
            "tests",
            "shared",
            "docs",
            "config"
        ],
        "role_output_roots": {
            "solution_architect": ["docs/architecture"],
            "api_designer": ["contracts", "docs/api"],
            "database_architect": ["database"],
            "security_engineer": ["security", "backend/middleware"],
            "backend_engineer": ["backend"],
            "frontend_engineer": ["frontend"],
            "devops_engineer": ["devops", "infra"],
            "qa_engineer": ["tests"],
            "ml_engineer": ["backend/ml"]
        },
        "notes": [
            "All agents may write anywhere under workspace/, but should prefer their role output roots.",
            "Use production-style paths (backend/, frontend/, database/, infra/, tests/) instead of role-named folders."
        ]
    }


def normalize_layers_common_sense(ledger_data: Dict) -> None:
    """Normalize layers with minimal count while preserving practical execution order."""
    if not isinstance(ledger_data, dict):
        return

    spec = ledger_data.get("agent_specifications")
    if not isinstance(spec, dict):
        return

    required_agents = spec.get("required_agents", [])
    if not isinstance(required_agents, list) or not required_agents:
        return

    role_to_agent = {}
    for a in required_agents:
        role = _extract_role(a)
        if not role:
            continue
        if isinstance(a, dict):
            role_to_agent[role] = a
        else:
            role_to_agent[role] = {"role": role}
    if not role_to_agent:
        return

    raw_layers = spec.get("layers", []) or []
    flattened_roles = []

    for layer in raw_layers:
        if isinstance(layer, list):
            entries = layer
        elif isinstance(layer, dict):
            entries = layer.get("agents", []) if isinstance(layer.get("agents", []), list) else []
        else:
            entries = []

        for entry in entries:
            role = _extract_role(entry)

            if role in role_to_agent and role not in flattened_roles:
                flattened_roles.append(role)

    # Ensure all required roles are included even if model missed some in layers
    for role in role_to_agent:
        if role not in flattened_roles:
            flattened_roles.append(role)

    # Sort by inferred phase, stable within same phase by original appearance
    original_order = {role: idx for idx, role in enumerate(flattened_roles)}
    flattened_roles.sort(key=lambda r: (_infer_agent_phase(role_to_agent.get(r, {"role": r})), original_order.get(r, 10**6)))

    normalized_layers = []
    current_layer = []
    current_phase = None
    for role in flattened_roles:
        phase = _infer_agent_phase(role_to_agent.get(role, {"role": role}))
        if current_phase is None or phase == current_phase:
            current_layer.append(role)
            current_phase = phase
        else:
            if current_layer:
                normalized_layers.append(current_layer)
            current_layer = [role]
            current_phase = phase
    if current_layer:
        normalized_layers.append(current_layer)

    spec["layers"] = enforce_api_designer_first_layer(normalized_layers)


def enforce_api_designer_first_layer(layers: List[List[str]]) -> List[List[str]]:
    """Ensure api_designer executes first and alone when present."""
    if not isinstance(layers, list):
        return layers

    has_api_designer = any(
        isinstance(layer, list) and any(role == AgentRole.API_DESIGNER.value for role in layer)
        for layer in layers
    )
    if not has_api_designer:
        return layers

    cleaned_layers: List[List[str]] = []
    for layer in layers:
        if not isinstance(layer, list):
            continue
        filtered = [r for r in layer if isinstance(r, str) and r != AgentRole.API_DESIGNER.value]
        if filtered:
            cleaned_layers.append(filtered)

    return [[AgentRole.API_DESIGNER.value]] + cleaned_layers

class TaskLedger:
    """
    A comprehensive task ledger generated by Director AI.
    Contains all project metadata, agent specifications, and
    Agent Execution Graph.
    """

    def __init__(self, user_intent: str, owner_id: str):
        project_id = str(uuid.uuid4())[:8]
        self.data = {
            "project_id": project_id,
            "owner_id": owner_id,
            "collaborators": [],
            "user_intent": user_intent,
            "project_name": "",
            "project_description": "",
            "functional_requirements": [],
            "non_functional_requirements": {
                "performance": "Standard",
                "sla": "99.9%",
                "budget": "Optimized",
                "scalability": "High",
                "availability": "High",
                "security_level": "Enterprise"
            },
            "tech_constraints": {
                "preferred_stack": [],
                "forbidden_services": [],
                "required_compliance": []
            },
            "integration_targets": [],
            "timeline_budget": "",
            "architecture_pattern": "",
            "design_principles": [],
            "guardrail_overrides": [],
            "operation_log": [],
            "revision_history": [],
            "status": "DRAFT",
            # Agent DAG Specification
            "agent_specifications": {
                "required_agents": [],  # List of {role, specialty, count}
                "layers": [],  # List[List[str]] execution groups
            },
            "technology_stack": {
                "backend_frameworks": [],
                "frontend_frameworks": [],
                "databases": [],
                "messaging_systems": [],
                "cloud_services": [],
                "development_tools": []
            },
            "feature_catalog": [],
            "layer_onboarding": [],
            "workspace_layout": {
                "directories": [],
                "role_output_roots": {},
                "notes": []
            },
            "api_specifications": [],
            "database_schemas": [],
            "security_requirements": [],
            "testing_strategy": [],
        }

    def add_revision(self, summary: str):
        self.data["revision_history"].append({
            "timestamp": datetime.now(datetime.timezone.utc).isoformat(),
            "change_summary": summary
        })
    
    
    
    def update_agents(self, agents: List[Dict]):
        """Update the agent specifications in the ledger."""
        self.data["agent_specifications"]["required_agents"] = agents
        
    def to_json(self):
        return self.data
    
    def normalize_dependencies(self, depends_on, agents):
        """Backward compatibility helper for legacy ledgers using dependencies."""
        # Handle agents with either agent_name or role field
        all_agents = set()
        for a in agents:
            role = _extract_role(a)
            if role:
                all_agents.add(role)

        for agent in all_agents:
            depends_on.setdefault(agent, [])

        return depends_on

    def validate_dependencies(self, depends_on, agents):
        valid = {
            _extract_role(a)
            for a in agents
            if _extract_role(a)
        }

        for agent, deps in depends_on.items():
            if agent not in valid:
                raise ValueError(f"Unknown agent: {agent}")
            for dep in deps:
                if dep not in valid:
                    raise ValueError(f"{agent} depends on unknown {dep}")

    def apply_coexecution_policy(self, depends_on, agents):
        """
        General policy: strongly-coupled implementation roles should co-execute.

        For now, backend + frontend are aligned to the same dependency frontier
        by sharing the union of their prerequisites.
        """
        roles = {
            _extract_role(a)
            for a in agents
            if _extract_role(a)
        }

        coupled_groups = [
            ["backend_engineer", "frontend_engineer"],
        ]

        for group in coupled_groups:
            if not all(role in roles for role in group):
                continue

            union_deps = set()
            for role in group:
                union_deps.update(depends_on.get(role, []))

            # Never depend on a peer in the same coupled group; that creates cycles
            union_deps = {d for d in union_deps if d not in group}

            for role in group:
                depends_on[role] = sorted(union_deps)

        return depends_on
    
    def build_execution_layers(self):
        spec = self.data.get("agent_specifications", {})
        agents = spec.get("required_agents", [])
        roles = {_extract_role(a) for a in agents if _extract_role(a)}

        layers = spec.get("layers", []) or []
        if layers:
            seen = set()
            normalized_layers = []
            for idx, layer_entry in enumerate(layers, 1):
                if isinstance(layer_entry, list):
                    layer = layer_entry
                elif isinstance(layer_entry, dict):
                    layer_agents = layer_entry.get("agents", [])
                    if not isinstance(layer_agents, list):
                        raise ValueError(f"Layer {idx} must have 'agents' as a list")
                    layer = []
                    for agent_ref in layer_agents:
                        if isinstance(agent_ref, str):
                            layer.append(agent_ref)
                        elif isinstance(agent_ref, dict):
                            role = agent_ref.get("role")
                            if not role:
                                raise ValueError(f"Layer {idx} contains an agent object without role")
                            layer.append(role)
                        else:
                            raise ValueError(f"Layer {idx} has unsupported agent entry type")
                else:
                    raise ValueError(f"Layer {idx} must be a list or object with agents")

                if len(layer) == 0:
                    raise ValueError(f"Layer {idx} cannot be empty")
                normalized_layer = []
                for role_entry in layer:
                    role = _extract_role(role_entry)
                    if not role:
                        raise ValueError(f"Layer {idx} has invalid agent entry: {role_entry}")
                    if role not in roles:
                        raise ValueError(f"Layer {idx} contains unknown role: {role}")
                    if role in seen:
                        raise ValueError(f"Role appears in multiple layers: {role}")
                    seen.add(role)
                    normalized_layer.append(role)
                normalized_layers.append(normalized_layer)

            missing = roles - seen
            if missing:
                raise ValueError(f"Layers missing required agents: {sorted(missing)}")
            return enforce_api_designer_first_layer(normalized_layers)

        # Backward compatibility: derive layers from legacy dependencies if layers absent.
        legacy_deps = spec.get("agent_dependencies", {})
        depends_on = self.normalize_dependencies(legacy_deps, agents)
        depends_on = self.apply_coexecution_policy(depends_on, agents)
        self.validate_dependencies(depends_on, agents)

        derived_layers = []
        remaining = set(depends_on.keys())
        while remaining:
            ready = [
                node for node in remaining
                if all(dep not in remaining for dep in depends_on[node])
            ]
            if not ready:
                raise ValueError("Cycle detected in dependencies")

            # Parallelize all currently-ready agents in one layer to minimize layer count.
            derived_layers.append(ready)
            for node in ready:
                remaining.remove(node)

        return enforce_api_designer_first_layer(derived_layers)

class LedgerTools:
    """Tools for managing the task ledger"""
    
    def __init__(self, workspace_dir=WORKSPACE_DIR):
        self.workspace_dir = workspace_dir
        self.follow_up_answers = {}  # Store follow-up question answers
    
    def read_task_ledger(self, project_id: str) -> str:
        """Read the task ledger from file"""
        try:
            ledger_path = os.path.join(self.workspace_dir, f"ledger_{project_id}.json")
            if not os.path.exists(ledger_path):
                return f"ERROR: Ledger file not found at {ledger_path}"
            
            with open(ledger_path, 'r') as f:
                ledger_data = json.load(f)
            return json.dumps(ledger_data, indent=2)
        except Exception as e:
            return f"ERROR: Failed to read ledger: {str(e)}"
    
    def write_task_ledger(self, project_id: str, ledger_data: str) -> str:
        """Write the task ledger to file"""
        try:
            ledger_path = os.path.join(self.workspace_dir, f"ledger_{project_id}.json")
            
            # Validate JSON
            if isinstance(ledger_data, str):
                parsed_data = json.loads(ledger_data)
            else:
                parsed_data = ledger_data
            
            # Write to file
            with open(ledger_path, 'w') as f:
                json.dump(parsed_data, f, indent=2)
            
            return f"✅ Successfully wrote ledger to {ledger_path}"
        except json.JSONDecodeError as e:
            return f"ERROR: Invalid JSON in ledger data: {str(e)}"
        except Exception as e:
            return f"ERROR: Failed to write ledger: {str(e)}"
    
    def validate_ledger(self, ledger_data: str) -> str:
        """Validate ledger for consistency and correctness"""
        try:
            if isinstance(ledger_data, str):
                data = json.loads(ledger_data)
            else:
                data = ledger_data
            
            errors = []
            warnings = []
            
            # Check required fields
            required_fields = ["project_id", "user_intent", "agent_specifications"]
            for field in required_fields:
                if field not in data:
                    errors.append(f"Missing required field: {field}")
            
            # Validate agent specifications
            if "agent_specifications" in data:
                agents = data["agent_specifications"].get("required_agents", [])
                layers = data["agent_specifications"].get("layers", [])
                deps = data["agent_specifications"].get("agent_dependencies", {})
                
                # Check all agents have required fields
                for agent in agents:
                    role = _extract_role(agent)
                    if not role:
                        errors.append(f"Agent missing role: {agent}")
                        continue
                    if isinstance(agent, dict) and "instructions" not in agent:
                        warnings.append(f"Agent {role} missing 'instructions'")

                valid_agents = {_extract_role(a) for a in agents if _extract_role(a)}

                # Preferred model: explicit layers
                if layers:
                    if not isinstance(layers, list):
                        errors.append("agent_specifications.layers must be a list")
                    else:
                        seen = set()
                        for idx, layer_entry in enumerate(layers, 1):
                            if isinstance(layer_entry, list):
                                layer = layer_entry
                            elif isinstance(layer_entry, dict):
                                layer = layer_entry.get("agents", [])
                                if not isinstance(layer, list):
                                    errors.append(f"Layer {idx} has invalid 'agents' format")
                                    continue
                            else:
                                errors.append(f"Layer {idx} must be a list or object with 'agents'")
                                continue

                            if len(layer) == 0:
                                errors.append(f"Layer {idx} cannot be empty")
                            for role_entry in layer:
                                role = _extract_role(role_entry)
                                if not role:
                                    errors.append(f"Layer {idx} has invalid agent entry: {role_entry}")
                                    continue
                                if role not in valid_agents:
                                    errors.append(f"Layer {idx} references unknown agent: {role}")
                                if role in seen:
                                    errors.append(f"Agent appears in multiple layers: {role}")
                                seen.add(role)

                        missing = valid_agents - seen
                        if missing:
                            errors.append(f"Layers missing agents: {sorted(missing)}")
                else:
                    # Backward compatibility for legacy dependency ledgers.
                    for agent_name, dependencies in deps.items():
                        if agent_name not in valid_agents:
                            errors.append(f"Unknown agent in dependencies: {agent_name}")
                        for dep in dependencies:
                            if dep not in valid_agents:
                                errors.append(f"Agent {agent_name} depends on unknown agent: {dep}")

                    if self._has_cycles(deps):
                        errors.append("Cycle detected in agent dependencies")
                    else:
                        warnings.append("Using legacy agent_dependencies. Prefer agent_specifications.layers.")
            
            # Compile results
            if errors:
                result = "❌ VALIDATION FAILED:\n"
                for err in errors:
                    result += f"  - {err}\n"
            else:
                result = "✅ VALIDATION PASSED"
            
            if warnings:
                result += "\n⚠️ WARNINGS:\n"
                for warn in warnings:
                    result += f"  - {warn}\n"
            
            return result
        
        except json.JSONDecodeError as e:
            return f"ERROR: Invalid JSON: {str(e)}"
        except Exception as e:
            return f"ERROR: Validation failed: {str(e)}"
    
    def _has_cycles(self, deps: Dict[str, List[str]]) -> bool:
        """Check if dependency graph has cycles"""
        visited = set()
        rec_stack = set()
        
        def has_cycle_dfs(node):
            visited.add(node)
            rec_stack.add(node)
            
            for neighbor in deps.get(node, []):
                if neighbor not in visited:
                    if has_cycle_dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True
            
            rec_stack.remove(node)
            return False
        
        for node in deps:
            if node not in visited:
                if has_cycle_dfs(node):
                    return True
        
        return False
    
    def ask_follow_up_question(self, question: str) -> str:
        """Ask a follow-up question to the user and record the answer"""
        try:
            print(f"\n❓ Follow-up Question: {question}")
            answer = input("✍️  Your answer: ").strip()
            print(f"✅ Recorded\n")
            return f"User answered: {answer}"
        except Exception as e:
            return f"ERROR: Failed to get user input: {str(e)}"


class DirectorToolRegistry:
    """Registry combining general tools and ledger-specific tools"""
    
    def __init__(self):
        from tooly import ToolConfig
        tool_config = ToolConfig(allowed_root=WORKSPACE_DIR, timeout=60)
        self.general_tools = ToolRegistry(config=tool_config)
        self.ledger_tools = LedgerTools(workspace_dir=WORKSPACE_DIR)
    
    def get_tool_definitions(self):
        """Get all tool definitions including ledger tools"""
        tools = self.general_tools.get_tool_definitions()
        
        # Add ledger-specific tools
        ledger_tools_defs = [
            {
                "type": "function",
                "function": {
                    "name": "read_task_ledger",
                    "description": "Read the current task ledger from the workspace",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "project_id": {
                                "type": "string",
                                "description": "The project ID of the ledger to read"
                            }
                        },
                        "required": ["project_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "write_task_ledger",
                    "description": "Write the updated task ledger to the workspace",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "project_id": {
                                "type": "string",
                                "description": "The project ID"
                            },
                            "ledger_data": {
                                "type": "string",
                                "description": "The complete ledger data as JSON string"
                            }
                        },
                        "required": ["project_id", "ledger_data"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "validate_ledger",
                    "description": "Validate ledger for consistency and correctness",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ledger_data": {
                                "type": "string",
                                "description": "The ledger data to validate as JSON string"
                            }
                        },
                        "required": ["ledger_data"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "ask_follow_up_question",
                    "description": "Ask the user a follow-up question and get their answer",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "question": {
                                "type": "string",
                                "description": "The follow-up question to ask the user"
                            }
                        },
                        "required": ["question"]
                    }
                }
            }
        ]
        
        return tools + ledger_tools_defs
    
    def execute_tool(self, function_name, function_args):
        """Execute a tool by name"""
        # Try ledger tools first
        if function_name == "read_task_ledger":
            return self.ledger_tools.read_task_ledger(function_args.get("project_id", ""))
        elif function_name == "write_task_ledger":
            return self.ledger_tools.write_task_ledger(
                function_args.get("project_id", ""),
                function_args.get("ledger_data", "")
            )
        elif function_name == "validate_ledger":
            return self.ledger_tools.validate_ledger(function_args.get("ledger_data", ""))
        elif function_name == "ask_follow_up_question":
            return self.ledger_tools.ask_follow_up_question(function_args.get("question", ""))
        else:
            # Fall back to general tools
            return self.general_tools.execute_tool(function_name, function_args)


class DirectorAI:

    def __init__(self):
        self.client = AzureOpenAI(
            api_key = AZURE_OPENAI_KEY,
            api_version = AZURE_API_VERSION,
            azure_endpoint = AZURE_ENDPOINT
        )
        self.tools_registry = DirectorToolRegistry()
    
    def get_tools(self):
        """Get tool definitions for the API"""
        return self.tools_registry.get_tool_definitions()
    
    def clarify_intent(self, ledger: TaskLedger, iteration: int, previous_ledger: Dict = None) -> Dict:
        """
        Translates informal user intent into structured requirements.
        Uses tools to read, validate, and write the task ledger.
        Implements file-as-source-of-truth pattern.
        """
        project_id = ledger.data["project_id"]
        
        system_prompt = f"""You are the Director Agent for Agentic Nexus - a no-code platform for building entire applications from natural language.

YOUR CORE TASK:
Refine the task ledger by analyzing user intent, determining required agents, specifying technology stack,
and preparing strong coordination artifacts for execution layers.

⚠️ PROJECT ID: {project_id}
⚠️ ALWAYS USE THIS PROJECT ID IN TOOL CALLS

WORKFLOW - YOU MUST USE TOOLS:
1. Use read_task_ledger(project_id="{project_id}") to load current state
2. Analyze what needs improvement based on user intent
3. Prepare JSON updates for ledger fields
4. Use validate_ledger() to check consistency
5. Use write_task_ledger(project_id="{project_id}", ledger_data=...) to persist if valid
6. When complete, set status to "DONE"

AVAILABLE AGENT ROLES: {', '.join([r.value for r in AgentRole])}

CONSISTENCY RULES:
- Use agent_specifications.layers for execution ordering (NOT agent_dependencies)
- Each layer is an array of role names
- Every required agent role must appear in exactly one layer
- If api_designer exists, it MUST be in layer 1 and MUST run alone in that layer
- Layers should be ordered logically in order of execution from first to last - agents that should execute first should be put in earlier layers
- Keep total number of layers as low as practical by parallelizing compatible agents
- If an agent would mostly wait on another agent's deliverable, place it in a later layer
- If two agents can coordinate effectively with bounded dependency risk, place them in the same layer
- Each agent needs: role, instructions
- Minimize agent count (quality over quantity)
- Match technology stack to requirements
- Populate feature_catalog with ALL expected product features/capabilities.
- Populate layer_onboarding with one entry per layer. Each entry must include:
    • layer_index
    • stage_name
    • project_context
    • objective
    • required_outcomes (WHAT must be delivered)
    • role_expectations (per-role responsibilities for this stage)
    • coordination_expectations (group blackboard discussion and agreement requirements)
    • handoff_contracts (interfaces/contracts expected from this layer)
    • next_stage_readiness (what must be ready for the next layer)
- Populate workspace_layout with:
    • directories (production-style folders like backend/, frontend/, database/, infra/, tests/)
    • role_output_roots (where each role should primarily write)
    • notes (pathing conventions and constraints)
- Do NOT prescribe exact implementation internals (e.g., concrete API spec code/tasks) in the ledger.
- The ledger should state WHAT needs to be done; agents decide HOW via detailed blackboard discussion.
- Status flow: "DRAFT" (building) → "DONE" (ready for execution)

Return JSON with only the fields you update. The tool will validate before persisting."""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Iteration {iteration} - Use project_id '{project_id}'. User intent: {ledger.data['user_intent']}"}
        ]     
        
        _throttle_model_call()
        response = self.client.chat.completions.create(
            model = AZURE_MODEL_DEPLOYMENT,
            messages=messages,
            tools=self.get_tools(),
            tool_choice="auto",
            temperature=0.7
        )
        
        assistant_message = response.choices[0].message
        messages.append(assistant_message)
        
        # Handle tool calls
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
                
                print(f"  🔧 Tool: {function_name}")
                result = self.tools_registry.execute_tool(function_name, function_args)
                print(f"  📤 Result: {result[:200]}...")
                
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result
                })
            
            # Get final response after tool calls
            _throttle_model_call()
            final_response = self.client.chat.completions.create(
                model = AZURE_MODEL_DEPLOYMENT,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.7
            )
            
            final_content = final_response.choices[0].message.content
        else:
            final_content = assistant_message.content
        
        try:
            updated_data = json.loads(final_content)
            return updated_data
        except json.JSONDecodeError:
            print(f"  ⚠️ Failed to parse final response as JSON")
            return {}
    
    def clarify_intent_with_thought(self, ledger: TaskLedger, iteration: int, previous_ledger: Dict = None, clarification_answers: Dict = None) -> tuple:
        """
        Refine task ledger with visible thought process and follow-up questions support.
        Returns (ledger_data, thought_process, follow_up_questions_dict)
        Uses the working clarify_intent logic but adds thought process extraction.
        """
        project_id = ledger.data["project_id"]
        
        # Build clarification context
        clarification_context = ""
        if clarification_answers:
            clarification_context = "\n\n📝 USER CLARIFICATIONS (from earlier):"
            for key, answer in clarification_answers.items():
                clarification_context += f"\n  • {key}: {answer}"
        
        system_prompt = f"""You are the Director Agent for Agentic Nexus - a no-code platform for building entire applications from natural language.

YOUR CORE TASK:
Refine the task ledger by analyzing user intent, determining required agents, specifying technology stack,
and producing detailed layer onboarding guidance.

⚠️ PROJECT ID: {project_id}
⚠️ ALWAYS USE THIS PROJECT ID IN TOOL CALLS

MANDATORY WORKFLOW - YOU MUST FOLLOW THIS EXACTLY:
1. Use read_task_ledger(project_id="{project_id}") to load current state
2. Analyze the current state and identify what needs to be improved
3. Explain your reasoning: what fields are missing or need updating
4. Prepare a COMPLETE JSON object with ALL fields from the current ledger, plus your updates
5. ALWAYS call: write_task_ledger(project_id="{project_id}", ledger_data=<YOUR_COMPLETE_JSON_AS_STRING>)
6. Use validate_ledger(ledger_data=<YOUR_JSON>) to verify consistency
7. Return the complete updated ledger as JSON

EXECUTION STYLE:
- Build a COMPLETE, executable ledger as early as possible (preferably first iteration).
- Subsequent iterations should be lightweight refinements only if needed.

CRITICAL RULES:
✓ ALWAYS call write_task_ledger() - NEVER skip this
✓ Include ALL fields in your JSON response (copy from current + add updates)
✓ Prefer agent_specifications.layers and minimize total layers by parallelizing where sensible
✓ Put heavily blocked/waiting agents in later layers; keep decently coordinating agents together
✓ Ensure every required agent role appears exactly once in layers
✓ Populate feature_catalog with ALL expected project features/capabilities
✓ Populate layer_onboarding with one detailed onboarding entry per execution layer
✓ In layer_onboarding, specify WHAT each layer must deliver, per-role expectations, and next-stage readiness outputs
✓ Populate workspace_layout with production-style directories and role_output_roots per role
✓ Do NOT prescribe exact implementation internals (e.g., concrete API spec code tasks) in ledger fields
✓ Return ONLY valid JSON - no explanations outside JSON
✓ Use null/empty arrays for fields with no data yet

AVAILABLE AGENT ROLES: {', '.join([r.value for r in AgentRole])}

USER CONTEXT:
{chr(10).join([f"  • {k}: {v}" for k, v in (clarification_answers or {}).items()])}{clarification_context}"""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Iteration {iteration} - Use project_id '{project_id}'. User intent: {ledger.data['user_intent']}"}
        ]     
        
        _throttle_model_call()
        response = self.client.chat.completions.create(
            model=AZURE_MODEL_DEPLOYMENT,
            messages=messages,
            tools=self.get_tools(),
            tool_choice="auto",
            temperature=0.7
        )
        
        assistant_message = response.choices[0].message
        messages.append(assistant_message)
        
        # Extract thought process from assistant's initial message (before tools are called)
        thought_process = ""
        if assistant_message.content:
            # Take the full initial message as reasoning
            thought_process = assistant_message.content.strip()
            # If it starts with { (JSON), it's the response, not reasoning
            if thought_process.startswith("{"):
                thought_process = ""
        
        # Variables to track
        ledger_data = None
        follow_up_questions = {}
        
        # Handle tool calls
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
                
                print(f"  🔧 Tool: {function_name}")
                
                # Show what we're doing for each tool
                if function_name == "read_task_ledger":
                    print(f"     → Reading ledger")
                elif function_name == "write_task_ledger":
                    ledger_str = function_args.get('ledger_data', '')
                    print(f"     → Writing {len(ledger_str)} chars of ledger")
                    try:
                        preview = json.loads(ledger_str)
                        agents = len(preview.get('agent_specifications', {}).get('required_agents', []))
                        print(f"     → Content: {agents} agents, status={preview.get('status')}")
                    except:
                        pass
                elif function_name == "validate_ledger":
                    print(f"     → Validating")
                
                result = self.tools_registry.execute_tool(function_name, function_args)
                print(f"  ✅ {result[:140]}")
                
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result
                })
            
            # Get final response after tool calls (JSON response only)
            _throttle_model_call()
            final_response = self.client.chat.completions.create(
                model=AZURE_MODEL_DEPLOYMENT,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.7
            )
            
            final_content = final_response.choices[0].message.content
        else:
            final_content = assistant_message.content
        
        # Parse and return results
        try:
            if final_content:
                updated_data = json.loads(final_content)
                ledger_data = updated_data
                
                # Check for follow-up questions in the parsed JSON
                if "follow_up_question" in updated_data:
                    follow_up_questions[1] = updated_data["follow_up_question"]
                if "follow_up_questions" in updated_data and isinstance(updated_data["follow_up_questions"], list):
                    for idx, q in enumerate(updated_data["follow_up_questions"], 1):
                        follow_up_questions[idx] = q
        except json.JSONDecodeError:
            print(f"  ⚠️ Failed to parse response as JSON")
            return None, thought_process, {}
        
        return ledger_data, thought_process, follow_up_questions

# Module-level test code moved to __main__ guard
if __name__ == "__main__":
    task = "Create an E-Commerce Website for a store that sells Electronic Appliances"
    ledger = TaskLedger(task, "Owner123")
    agent = DirectorAI()

def get_clarification_answers(questions: List[str]) -> Dict[int, str]:
    """Collect user answers to clarification questions"""
    answers = {}
    print("\n" + "="*70)
    print("DIRECTOR AGENT HAS QUESTIONS")
    print("="*70)
    
    for i, question in enumerate(questions, 1):
        print(f"\n❓ Question {i}: {question}")
        answer = input("✍️  Your answer: ").strip()
        answers[i] = answer
        print(f"✅ Recorded: {answer[:50]}...")
    
    return answers


def ask_clarification_questions(agent: 'DirectorAI', ledger: TaskLedger, project_id: str) -> Dict[int, str]:
    """First iteration: Agent asks clarifying questions"""
    print(f"\n{'='*70}")
    print(f"Iteration 1/N: CLARIFICATION PHASE")
    print(f"{'='*70}")
    
    system_prompt = f"""You are the Director Agent for Agentic Nexus - preparing to build a task ledger.

YOUR TASK:
Ask exactly 3 simple, clear questions to better understand the project requirements.

REQUIREMENTS:
- Ask exactly 3 questions (no more, no less)
- Keep questions simple and specific
- Focus on: scope, timeline, budget/constraints, or specific features
- Return ONLY a JSON object with this exact structure:

{{
  "questions": [
    "Question 1?",
    "Question 2?",
    "Question 3?"
  ],
  "thought_process": "Brief explanation of why you're asking these questions"
}}

Project intent: {ledger.data['user_intent']}"""
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Ask 3 clarification questions about this project: {ledger.data['user_intent']}"}
    ]
    
    _throttle_model_call()
    response = agent.client.chat.completions.create(
        model=AZURE_MODEL_DEPLOYMENT,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.7
    )
    
    try:
        response_data = json.loads(response.choices[0].message.content)
        questions = response_data.get("questions", [])
        thought_process = response_data.get("thought_process", "")
        
        if thought_process:
            print(f"\n🧠 Agent Thought Process:\n{thought_process}\n")
        
        # Get user answers
        answers = get_clarification_answers(questions)
        return answers
    except json.JSONDecodeError:
        print("❌ Failed to parse agent response")
        return {}


def execute_agent(task):
    """Execute the director agent to build the task ledger"""
    max_iterations = 4
    no_change_limit = 2
    
    # Initialize ledger file
    project_id = ledger.data["project_id"]
    ledger_path = os.path.join(WORKSPACE_DIR, f"ledger_{project_id}.json")
    
    # Save initial ledger to file (file is source of truth)
    try:
        with open(ledger_path, 'w') as f:
            json.dump(ledger.data, f, indent=2)
    except Exception as e:
        print(f"❌ Failed to initialize ledger: {e}")
        return
    
    print(f"\n📋 Task Ledger Configuration:")
    print(f"  Project ID: {project_id}")
    print(f"  Ledger Path: {ledger_path}")
    print(f"  Max Iterations: {max_iterations}\n")
    
    # Phase 1: Ask clarifying questions
    print("\n" + "="*70)
    print("PHASE 1: CLARIFICATION")
    print("="*70)
    clarification_answers = ask_clarification_questions(agent, ledger, project_id)
    
    # Format answers for agent context
    answers_context = "\n".join([f"{i}. {answer}" for i, answer in clarification_answers.items()])
    
    print("\n" + "="*70)
    print("PHASE 2: LEDGER REFINEMENT")
    print("="*70)
    
    previous_ledger = None
    no_change_count = 0
    
    for i in range(1, max_iterations + 1):
        print(f"\n{'='*70}")
        print(f"Iteration {i}/{max_iterations}")
        print(f"{'='*70}")
        
        # Get updated ledger from agent (with tools)
        # Agent uses file-as-source-of-truth pattern
        ledger_data, agent_thought, follow_up_answers = agent.clarify_intent_with_thought(
            ledger, i, previous_ledger, clarification_answers=clarification_answers
        )
        
        # Display agent's thought process
        print(f"\n🧠 Agent Reasoning:")
        if agent_thought and len(agent_thought.strip()) > 0:
            print(f"{agent_thought}")
        else:
            print("(Analyzing ledger...)")
        
        # Merge updates into current ledger
        if isinstance(ledger_data, dict) and ledger_data:
            deep_update(ledger.data, ledger_data)
        elif ledger_data is not None and not isinstance(ledger_data, dict):
            print("⚠️ Ignoring non-dict ledger update from model")

        # Normalize layer ordering using common-sense role semantics
        normalize_layers_common_sense(ledger.data)

        # Policy: implementation details (like concrete API specs) belong to agent-level coordination, not ledger.
        ledger.data["api_specifications"] = []

        # Ensure a feature catalog exists (fallback from functional requirements if omitted).
        if not isinstance(ledger.data.get("feature_catalog"), list):
            ledger.data["feature_catalog"] = []
        if not ledger.data.get("feature_catalog"):
            ledger.data["feature_catalog"] = list(ledger.data.get("functional_requirements", []))

        # Ensure workspace layout exists and is production-structured.
        workspace_layout = ledger.data.get("workspace_layout")
        if not isinstance(workspace_layout, dict):
            workspace_layout = default_workspace_layout()
        defaults = default_workspace_layout()
        directories = workspace_layout.get("directories", [])
        if not isinstance(directories, list):
            directories = []
        merged_dirs = []
        for d in defaults["directories"] + directories:
            if isinstance(d, str) and d.strip() and d not in merged_dirs:
                merged_dirs.append(d.strip().strip("/"))

        role_output_roots = workspace_layout.get("role_output_roots", {})
        if not isinstance(role_output_roots, dict):
            role_output_roots = {}
        for role_name, roots in defaults["role_output_roots"].items():
            if role_name not in role_output_roots:
                role_output_roots[role_name] = list(roots)
            elif isinstance(role_output_roots[role_name], str):
                role_output_roots[role_name] = [role_output_roots[role_name]]

        notes = workspace_layout.get("notes", [])
        if not isinstance(notes, list):
            notes = []
        merged_notes = []
        for n in defaults["notes"] + notes:
            if isinstance(n, str) and n.strip() and n not in merged_notes:
                merged_notes.append(n.strip())

        workspace_layout = {
            "directories": merged_dirs,
            "role_output_roots": role_output_roots,
            "notes": merged_notes,
        }
        ledger.data["workspace_layout"] = workspace_layout

        # Ensure layer onboarding exists for each explicit layer.
        onboarding = ledger.data.get("layer_onboarding", [])
        if not isinstance(onboarding, list):
            onboarding = []
        existing_layer_indexes = {
            int(item.get("layer_index"))
            for item in onboarding
            if isinstance(item, dict) and isinstance(item.get("layer_index"), int)
        }
        layers = ledger.data.get("agent_specifications", {}).get("layers", []) or []
        for idx, layer in enumerate(layers, start=1):
            if idx in existing_layer_indexes:
                continue
            layer_roles = layer if isinstance(layer, list) else []
            next_roles = []
            if idx < len(layers):
                next_layer = layers[idx]
                next_roles = next_layer if isinstance(next_layer, list) else []
            onboarding.append({
                "layer_index": idx,
                "stage_name": f"Layer {idx} Execution Stage",
                "project_context": {
                    "project_name": ledger.data.get("project_name", ""),
                    "project_description": ledger.data.get("project_description", ""),
                    "functional_features": list(ledger.data.get("feature_catalog", []) or ledger.data.get("functional_requirements", []))
                },
                "objective": f"Deliver layer {idx} outcomes for roles: {', '.join(layer_roles)}",
                "required_outcomes": [
                    "Implement all functional outcomes assigned to this layer.",
                    "Produce code artifacts in production-style paths under workspace/ (not role-named folders).",
                ],
                "role_expectations": [
                    f"{role}: deliver role responsibilities with clear file-level outputs in {', '.join((workspace_layout.get('role_output_roots', {}).get(role, [role])))} and assumptions documented"
                    for role in layer_roles
                ],
                "coordination_expectations": [
                    "Post detailed implementation plans on layer blackboard before coding.",
                    "Read and reconcile peer plans; publish follow-up alignment agreement.",
                    "Use Service Bus only for one-to-one questions; blackboard for group alignment.",
                ],
                "handoff_contracts": [
                    "Publish file paths and interface assumptions in layer blackboard.",
                    "Keep outputs compatible with upstream/downstream layer expectations.",
                ],
                "next_stage_readiness": [
                    "All required outcomes in this stage are implemented and documented.",
                    "Known constraints/open assumptions are explicitly listed for handoff.",
                    f"Downstream consumers ({', '.join(next_roles) if next_roles else 'finalization/review'}) can proceed without ambiguity."
                ]
            })
        ledger.data["layer_onboarding"] = onboarding
        
        # Check if ledger changed (for early termination)
        current_json = json.dumps(ledger.data, sort_keys=True)
        if previous_ledger is not None:
            previous_json = json.dumps(previous_ledger, sort_keys=True)
            if current_json == previous_json:
                no_change_count += 1
                print(f"⚠️  No changes detected ({no_change_count}/{no_change_limit})")
            else:
                no_change_count = 0  # Reset counter on changes
        
        previous_ledger = json.loads(current_json)
        
        # Save ledger after each iteration (file = source of truth)
        try:
            with open(ledger_path, 'w') as f:
                json.dump(ledger.data, f, indent=2)
            print(f"✅ Ledger saved")
        except Exception as e:
            print(f"❌ Failed to save ledger: {e}")

        # Check if done (stop early when valid)
        validation_result = agent.tools_registry.ledger_tools.validate_ledger(ledger.data)
        validation_ok = validation_result.startswith("✅")

        if ledger.data.get("status") == "DONE" and validation_ok:
            print(f"\n✅ Task ledger marked DONE and validated at iteration {i}")
            break

        if no_change_count >= no_change_limit and validation_ok:
            print(f"\n✅ Stopping early: stable validated ledger for {no_change_count} iteration(s)")
            break
    else:
        print(f"\n⚠️ Max iterations ({max_iterations}) reached, status: {ledger.data.get('status')}")

    # Export per-layer onboarding docs for agent execution visibility.
    try:
        onboarding_dir = os.path.join(WORKSPACE_DIR, "layer_onboarding")
        os.makedirs(onboarding_dir, exist_ok=True)
        onboarding_entries = ledger.data.get("layer_onboarding", []) or []
        for entry in onboarding_entries:
            if not isinstance(entry, dict):
                continue
            layer_index = entry.get("layer_index")
            if not isinstance(layer_index, int):
                continue
            path = os.path.join(onboarding_dir, f"layer_{layer_index}.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# Layer {layer_index} Onboarding\n\n")
                if entry.get("stage_name"):
                    f.write(f"## Stage Name\n{entry.get('stage_name')}\n\n")

                project_context = entry.get("project_context", {}) if isinstance(entry.get("project_context", {}), dict) else {}
                if project_context:
                    f.write("## Project Context\n")
                    if project_context.get("project_name"):
                        f.write(f"- Project: {project_context.get('project_name')}\n")
                    if project_context.get("project_description"):
                        f.write(f"- Description: {project_context.get('project_description')}\n")
                    features = project_context.get("functional_features", []) or []
                    if features:
                        f.write("- Expected features for overall project:\n")
                        for feat in features:
                            f.write(f"  - {feat}\n")
                    f.write("\n")

                layout = ledger.data.get("workspace_layout", {}) if isinstance(ledger.data.get("workspace_layout", {}), dict) else {}
                directories = layout.get("directories", []) if isinstance(layout.get("directories", []), list) else []
                role_roots = layout.get("role_output_roots", {}) if isinstance(layout.get("role_output_roots", {}), dict) else {}
                notes = layout.get("notes", []) if isinstance(layout.get("notes", []), list) else []
                if directories or role_roots or notes:
                    f.write("## Workspace Layout (Production Paths)\n")
                    if directories:
                        f.write("- Planned directories:\n")
                        for d in directories:
                            f.write(f"  - {d}\n")
                    layer_roles = entry.get("role_expectations", []) or []
                    if role_roots:
                        f.write("- Role output roots:\n")
                        for role_name, roots in role_roots.items():
                            if isinstance(roots, str):
                                roots = [roots]
                            f.write(f"  - {role_name}: {', '.join(roots)}\n")
                    if notes:
                        f.write("- Conventions:\n")
                        for n in notes:
                            f.write(f"  - {n}\n")
                    f.write("\n")

                f.write(f"## Objective\n{entry.get('objective', '')}\n\n")
                f.write("## Required Outcomes\n")
                for item in entry.get("required_outcomes", []) or []:
                    f.write(f"- {item}\n")
                f.write("\n## Role Expectations\n")
                for item in entry.get("role_expectations", []) or []:
                    f.write(f"- {item}\n")
                f.write("\n## Coordination Expectations\n")
                for item in entry.get("coordination_expectations", []) or []:
                    f.write(f"- {item}\n")
                f.write("\n## Handoff Contracts\n")
                for item in entry.get("handoff_contracts", []) or []:
                    f.write(f"- {item}\n")
                f.write("\n## Next Stage Readiness Checklist\n")
                for item in entry.get("next_stage_readiness", []) or []:
                    f.write(f"- {item}\n")
        print(f"✅ Layer onboarding docs exported to {onboarding_dir}")

        layout = ledger.data.get("workspace_layout", {}) if isinstance(ledger.data.get("workspace_layout", {}), dict) else {}
        for d in (layout.get("directories", []) or []):
            if not isinstance(d, str) or not d.strip():
                continue
            rel = d.strip().strip("/")
            os.makedirs(os.path.join(WORKSPACE_DIR, rel), exist_ok=True)
        print("✅ Workspace layout directories initialized")
    except Exception as e:
        print(f"⚠️ Failed to export layer onboarding docs: {e}")

if __name__ == "__main__":
    print("\n" + "="*70)
    print("EXECUTION COMPLETE")
    print("="*70)

    execute_agent(task)

    print("\n📋 Final Task Ledger:")
    print("="*70)
    print(json.dumps(ledger.data, indent=2))

    print("\n🔄 Agent Execution Layers (Parallel Groups):")
    print("="*70)
    try:
        execution_layers = ledger.build_execution_layers()
        for i, layer in enumerate(execution_layers, 1):
            print(f"  Layer {i}: {layer}")
    except ValueError as e:
        print(f"  ❌ Error building execution layers: {e}")


        """
review_agent.py - Automated review agent for second development iteration

Scans generated agent workspaces, records issues into shared issues tracker,
and marks which agent must wake up to fix each issue.
"""


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
    
    """
agent_orchestrator_v3.py - Multi-Agent Orchestration with GeneralAgent Framework

IMPROVEMENTS FROM V2:
1. Uses GeneralAgent framework for each role (full tool suite)
2. Agents can read other agents' output files directly
3. Agents have access to: read_file, write_file, run_command, check_syntax, etc.
4. Cross-layer context includes actual file contents (not text descriptions)
5. Proper iteration loops with error recovery
6. Agents can validate their code before finalizing
7. Better coordination through actual code inspection

ARCHITECTURE:
- Layer 1: Database architect, Security engineer (parallel)
  └─ Agents generate files in production paths under workspace/ (backend/, frontend/, database/, etc.)
- Layer 2: Backend engineer (reads database schema from Layer 1)
  └─ Can read_file() to see exact table names, columns
- Layer 3: Frontend engineer (reads backend API schema from Layer 2)
  └─ Can read_file() to see actual endpoints and data formats
- Layer 4: QA engineer (reads all code from previous layers)
  └─ Generates tests that match actual implementation
"""

import json
import os
import time
import threading
import ast
import random
import subprocess
import re
import hashlib
import urllib.request
import urllib.error
from urllib.parse import urlparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
try:
    import fcntl  # Linux only
except ImportError:
    fcntl = None  # Windows fallback

# Merged into agents_combined — import from this module directly
from issues_tracker import get_issues_tracker, set_issues_tracker, IssuesTracker
# Merged into agents_combined — ReviewAgent defined above
from service_bus_coordination import ServiceBusCoordinator
from dotenv import load_dotenv

load_dotenv()

WORKSPACE_DIR = "./workspace"
NOTEBOOKS_DIR = os.path.join(WORKSPACE_DIR, "notebooks")
os.makedirs(WORKSPACE_DIR, exist_ok=True)
os.makedirs(NOTEBOOKS_DIR, exist_ok=True)

BLACKBOARD_PATH = os.path.join(WORKSPACE_DIR, "blackboard.md")
ISSUES_PATH = os.path.join(WORKSPACE_DIR, "issues.json")
LSP_PRECHECK_LOG_PATH = os.path.join(WORKSPACE_DIR, "lsp_precheck.log")
AGENT_LOCKS_DIR = os.path.join(WORKSPACE_DIR, "locks")
os.makedirs(AGENT_LOCKS_DIR, exist_ok=True)
LAYER_STAGGER_MIN_SECONDS = float(os.getenv("LAYER_STAGGER_MIN_SECONDS", "0.5"))
LAYER_STAGGER_MAX_SECONDS = float(os.getenv("LAYER_STAGGER_MAX_SECONDS", "2.5"))
AGENT_MAX_ATTEMPTS = int(os.getenv("AGENT_MAX_ATTEMPTS", "5"))
AGENT_MAX_ITERATIONS_MAIN = int(os.getenv("AGENT_MAX_ITERATIONS_MAIN", "90"))
AGENT_MAX_ITERATIONS_FIX = int(os.getenv("AGENT_MAX_ITERATIONS_FIX", "45"))
RUNTIME_SMOKE_TIMEOUT_SECONDS = int(os.getenv("RUNTIME_SMOKE_TIMEOUT_SECONDS", "25"))
FRONTEND_BUILD_TIMEOUT_SECONDS = int(os.getenv("FRONTEND_BUILD_TIMEOUT_SECONDS", "120"))
LAYER_MAX_WAIT_SECONDS = int(os.getenv("LAYER_MAX_WAIT_SECONDS", "900"))


class LayerSleepCoordinator:
  """In-layer sleep/wake coordination for agents blocked on peer work."""

  def __init__(self, agent_roles: List[str]):
    self._lock = threading.Lock()
    self._events: Dict[str, threading.Event] = {r: threading.Event() for r in agent_roles if r}
    self._sleep_state: Dict[str, Dict] = {}
    self._wake_state: Dict[str, Dict] = {}

  def request_sleep(self, role: str, reason: str, waiting_for_agent: str = "") -> None:
    with self._lock:
      if role not in self._events:
        self._events[role] = threading.Event()
      self._events[role].clear()
      self._sleep_state[role] = {
        "reason": reason,
        "waiting_for_agent": waiting_for_agent,
        "requested_at": datetime.now().isoformat(),
      }

  def wake(self, role: str, by_agent: str, resolution: str = "") -> None:
    with self._lock:
      if role not in self._events:
        self._events[role] = threading.Event()
      self._wake_state[role] = {
        "woken_by": by_agent,
        "resolution": resolution,
        "woken_at": datetime.now().isoformat(),
      }
      self._events[role].set()

  def wait_until_woken(self, role: str, timeout_seconds: int = 600) -> Optional[Dict]:
    with self._lock:
      event = self._events.get(role)
    if event is None:
      return None

    woken = event.wait(timeout_seconds)
    if not woken:
      return None

    with self._lock:
      event.clear()
      return {
        "sleep": self._sleep_state.get(role, {}),
        "wake": self._wake_state.get(role, {}),
      }


class LayerBlackboard:
    """Per-layer blackboard for agent coordination"""
    
    def __init__(self, layer_number, path=None):
        self.layer_number = layer_number
        if path is None:
            path = os.path.join(WORKSPACE_DIR, f"layer_{layer_number}_blackboard.md")
        self.path = path
        self.lock_path = os.path.join(AGENT_LOCKS_DIR, f"layer_{layer_number}_blackboard.lock")
        self.messages = []
        self._lock = threading.Lock()
        self._initialize()
    
    def _initialize(self):
        if not os.path.exists(self.path):
            self._write_file()
    
    def _write_file(self):
        """Write messages to file"""
        with open(self.path, 'w') as f:
            f.write(f"# Layer {self.layer_number} Coordination Blackboard\n\n")
            f.write(f"Last Updated: {datetime.now().isoformat()}\n\n")
            for msg in self.messages:
                timestamp = msg.get("timestamp", "")
                agent = msg.get("agent", "")
                content = msg.get("content", "")
                f.write(f"**[{agent}] {timestamp}**\n")
                f.write(f"{content}\n\n")
    
    def post(self, agent_name: str, content: str):
        """Post a message"""
        entry = {
            "agent": agent_name,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "content": content
        }
        with self._lock:
            lock_file = open(self.lock_path, "w")
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                self.messages.append(entry)
                self._write_file()
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()
    
    def read_all(self) -> str:
        """Get all messages as string"""
        with self._lock:
            lock_file = open(self.lock_path, "w")
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
                if not self.messages:
                    return f"Layer {self.layer_number} blackboard is empty."
                result = f"Layer {self.layer_number} Coordination:\n"
                for msg in self.messages:
                    result += f"- [{msg['agent']}]: {msg['content']}\n"
                return result
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()

    def message_count(self) -> int:
        """Return total number of layer messages"""
        with self._lock:
            return len(self.messages)

    def peer_message_count(self, agent_name: str) -> int:
      """Return number of messages written by peers (not this agent)."""
      with self._lock:
        return len([m for m in self.messages if m.get("agent") != agent_name])


class StructuredBlackboard:
    """Structured blackboard with three sections"""
    
    def __init__(self, path=BLACKBOARD_PATH):
        self.path = path
        self.sections = {
            "Discussions": [],
            "Issues": [],
            "Implementation plan": []
        }
        self._initialize()
    
    def _initialize(self):
        if not os.path.exists(self.path):
            self._write_file()
    
    def _write_file(self):
        """Write sections to file"""
        with open(self.path, 'w') as f:
            f.write("# Team Blackboard\n\n")
            f.write(f"Last Updated: {datetime.now().isoformat()}\n\n")
            f.write("---\n\n")
            
            for section_name in ["Discussions", "Issues", "Implementation plan"]:
                f.write(f"## {section_name}\n\n")
                entries = self.sections.get(section_name, [])
                for entry in entries:
                    timestamp = entry.get("timestamp", "")
                    agent = entry.get("agent", "")
                    content = entry.get("content", "")
                    f.write(f"**[{agent}] {timestamp}**\n")
                    f.write(f"{content}\n\n")
                f.write("---\n\n")
    
    def post(self, agent_name: str, section: str, content: str) -> bool:
        """Post to a section with file locking"""
        if section not in self.sections:
            return False
        
        lock_path = os.path.join(AGENT_LOCKS_DIR, "blackboard.lock")
        lock_file = open(lock_path, 'w')
        
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            
            entry = {
                "agent": agent_name,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "content": content
            }
            
            self.sections[section].append(entry)
            self._write_file()
            return True
        
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()
    
    def read_section(self, section: str) -> str:
        """Read entire section as formatted string"""
        if section not in self.sections:
            return ""
        
        entries = self.sections.get(section, [])
        if not entries:
            return f"{section} is empty."
        
        result = f"**{section}:**\n"
        for entry in entries:
            result += f"- [{entry['agent']} @ {entry['timestamp']}]: {entry['content']}\n"
        
        return result
    
    def clear(self):
        """Clear all sections"""
        for section in self.sections:
            self.sections[section] = []
        self._write_file()


# Custom agents that extend GeneralAgent with role-specific instructions
class DatabaseArchitectAgent(GeneralAgent):
    """Custom agent for database design"""
    
    def __init__(self, allowed_root=None):
        if allowed_root is None:
            allowed_root = WORKSPACE_DIR

        super().__init__(
            role="Database Architect",
            role_description="Design and implement database schemas for optimal performance and data integrity",
            specific_instructions="""
═══════════════════════════════════════════════════════════════════════════════
DATABASE ARCHITECT WORKFLOW - GENERIC SCHEMA DESIGN
═══════════════════════════════════════════════════════════════════════════════

PHASE 1: ANALYZE REQUIREMENTS (Iteration 1)
  ├─ Read upstream task description
  ├─ Identify what data the system needs to store
  ├─ List all entities and their core properties
  ├─ Map relationships between entities
  └─ Announce plan to blackboard

PHASE 2: DESIGN SCHEMA (Iterations 2-4)
  ├─ Create migrations/schema.sql with complete PostgreSQL DDL:
  │  ├─ All required tables based on entities identified
  │  ├─ Primary keys (SERIAL INT PRIMARY KEY)
  │  ├─ Foreign keys for relationships
  │  ├─ Constraints (NOT NULL, UNIQUE, CHECK)
  │  └─ Timestamps (created_at, updated_at)
  │
  ├─ Create migrations/seed_data.sql with sample data:
  │  ├─ Representative data for each table
  │  ├─ At least 5-10 rows per main entity table
  │  └─ Data that demonstrates relationships and constraints
  │
  ├─ Create config/db_config.js - Database connection configuration
  └─ Create config/db_setup.js - Script to initialize schema

PHASE 3: ENSURE QUALITY
  ├─ All required tables created
  ├─ All relationships properly modeled
  ├─ Constraints match business requirements
  ├─ Timestamps on all tables for audit trail
  ├─ Indexes on frequently searched columns (foreign keys, lookups)
  └─ Schema syntax is valid PostgreSQL

PHASE 4: VALIDATE (If database available)
  ├─ Run db_setup.js to test schema creation
  ├─ Verify seed data inserts without errors
  ├─ Check schema structure matches requirements
  └─ Document any issues or constraints

═══════════════════════════════════════════════════════════════════════════════
DATABASE DESIGN PATTERNS - FOLLOW THESE
═══════════════════════════════════════════════════════════════════════════════

Entity Definition:
  CREATE TABLE entity_name (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  );

Relationship (One-to-Many):
  child_table has:
    parent_id INT NOT NULL REFERENCES parent_table(id)

Many-to-Many Relationship (through junction table):
  CREATE TABLE entity1_entity2 (
    id SERIAL PRIMARY KEY,
    entity1_id INT NOT NULL REFERENCES entity1(id),
    entity2_id INT NOT NULL REFERENCES entity2(id),
    UNIQUE(entity1_id, entity2_id)
  );

Monetary Values:
  amount NUMERIC(10,2) NOT NULL CHECK (amount >= 0)

Status Enums:
  status VARCHAR(50) NOT NULL CHECK (status IN ('value1', 'value2'))

Timestamps:
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

Indexes:
  CREATE INDEX idx_table_column ON table(column);

═══════════════════════════════════════════════════════════════════════════════
OUTPUT FILES (relative paths in your workspace)
═══════════════════════════════════════════════════════════════════════════════

migrations/
  ├─ schema.sql - Complete DDL for all tables (200+ lines)
  └─ seed_data.sql - Representative test data (100+ lines)

config/
  ├─ db_config.js - Configuration for database connection
  └─ db_setup.js - Script to execute migrations

═══════════════════════════════════════════════════════════════════════════════
SUCCESS CRITERIA FOR YOUR DELIVERABLES
═══════════════════════════════════════════════════════════════════════════════

✅ All required entities have tables
✅ All relationships properly defined with foreign keys
✅ Primary keys on every table
✅ Timestamps (created_at, updated_at) on all tables
✅ Constraints match business rules (NOT NULL, UNIQUE, CHECK)
✅ Indexes on frequently accessed columns
✅ Seed data demonstrates all relationships
✅ Schema is syntactically valid PostgreSQL
✅ No errors running db_setup.js (if PostgreSQL available)

═══════════════════════════════════════════════════════════════════════════════
IF REQUIREMENTS OR CONTRACT ARE UNCLEAR - DO NOT GUESS
═══════════════════════════════════════════════════════════════════════════════

❓ Contract field/table unclear? → STOP and post blocking issue to blackboard
❓ Endpoint-to-table mapping unclear? → STOP and request api_designer clarification
❓ Constraint unclear? → STOP and request contract/schema alignment
❓ PostgreSQL not available? → You may still write migration files, but NEVER invent columns/relations

NEVER: "X not specified, using standard patterns"
INSTEAD: "Blocked by missing/ambiguous contract details; awaiting clarification"
""",
            allowed_root=allowed_root,
            timeout=120
        )
        self.workspace = allowed_root


class SecurityEngineerAgent(GeneralAgent):
    """Custom agent for security implementation"""
    
    def __init__(self, allowed_root=None):
        if allowed_root is None:
            allowed_root = WORKSPACE_DIR

        super().__init__(
            role="Security Engineer",
            role_description="Implement authentication, authorization, encryption, and security best practices",
            specific_instructions="""
═══════════════════════════════════════════════════════════════════════════════
SECURITY ENGINEER WORKFLOW - GENERIC SECURITY IMPLEMENTATION
═══════════════════════════════════════════════════════════════════════════════

PHASE 1: ANALYZE REQUIREMENTS (Iteration 1)
  ├─ Read database schema to understand data models
  ├─ Identify sensitive/protected data (PII, credentials, tokens)
  ├─ Identify critical operations that need authentication
  ├─ Announce security plan to blackboard
  └─ List security touchpoints to protect

PHASE 2: BUILD SECURITY LAYER (Iterations 2-5)
  ├─ middleware/authMiddleware.js - Token/authentication verification
  ├─ middleware/validation.js - Input validation and sanitization
  ├─ middleware/rateLimiter.js - Rate limiting for abuse prevention
  ├─ utils/encryption.js - Encryption utilities for sensitive data
  ├─ config/security.js - Centralized security configuration
  └─ tests/security.test.js - Security-focused tests

PHASE 3: IMPLEMENT CRITICAL SECURITY FEATURES
  ✅ Authentication (JWT or similar token-based system)
  ✅ Authorization (role-based or permission-based access)
  ✅ Password hashing (bcrypt or similar, never plain text)
  ✅ Input validation (prevent SQL injection, XSS)
  ✅ Rate limiting (prevent brute force, DDoS)
  ✅ Data encryption (for sensitive fields)
  ✅ CORS configuration (if frontend exists separately)
  ✅ No hardcoded secrets (use env variables)
  ✅ Secure headers (HTTPS, CSP, etc recommendations)

PHASE 4: INTEGRATE WITH SYSTEM
  ├─ Middleware integrates with main framework
  ├─ Encryption utilities are importable
  ├─ Rate limiting applies to vulnerable endpoints
  ├─ All secrets come from environment variables
  └─ Tests validate security logic works

═══════════════════════════════════════════════════════════════════════════════
SECURITY IMPLEMENTATION PATTERNS - FOLLOW THESE
═══════════════════════════════════════════════════════════════════════════════

Authentication Middleware:
  exports.authenticateToken = (req, res, next) => {
    const token = req.headers.authorization?.split(' ')[1];
    if (!token) return res.status(401).json({ error: 'No token' });
    try {
      const decoded = jwt.verify(token, process.env.JWT_SECRET);
      req.user = decoded;
      next();
    } catch (err) {
      res.status(403).json({ error: 'Invalid token' });
    }
  };

Input Sanitization:
  exports.sanitize = (input) => {
    // Remove/escape dangerous characters
    return String(input).replace(/[<>\"'&]/g, char => {
      const map = { '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;', '&': '&amp;' };
      return map[char];
    });
  };

Rate Limiting:
  const rateLimit = require('express-rate-limit');
  exports.loginLimiter = rateLimit({
    windowMs: 15 * 60 * 1000,
    max: 5,
    message: 'Too many login attempts'
  });

Encryption:
  const crypto = require('crypto');
  exports.encrypt = (text) => {
    const cipher = crypto.createCipher('aes-256-cbc', process.env.ENCRYPTION_KEY);
    return cipher.update(text, 'utf8', 'hex') + cipher.final('hex');
  };

═══════════════════════════════════════════════════════════════════════════════
OUTPUT FILES (relative paths in your workspace)
═══════════════════════════════════════════════════════════════════════════════

middleware/
  ├─ authMiddleware.js - Authentication/authorization verification
  ├─ validation.js - Input validation and sanitization
  └─ rateLimiter.js - Rate limiting configuration

utils/
  └─ encryption.js - Encryption and decryption utilities

config/
  └─ security.js - Centralized security settings (CORS, headers, etc)

tests/
  └─ security.test.js - Security-focused test cases

═══════════════════════════════════════════════════════════════════════════════
SUCCESS CRITERIA FOR YOUR DELIVERABLES
═══════════════════════════════════════════════════════════════════════════════

✅ Authentication works (tokens, sessions, or similar)
✅ Authorization works (can verify user permissions)
✅ Input sanitization prevents injection attacks
✅ Rate limiting configured on vulnerable endpoints
✅ Encryption utilities for sensitive data
✅ No hardcoded secrets (uses environment variables)
✅ Security headers configured
✅ Tests validate security logic
✅ Code follows security best practices

═══════════════════════════════════════════════════════════════════════════════
IF REQUIREMENTS OR CONTRACT ARE UNCLEAR - DO NOT GUESS
═══════════════════════════════════════════════════════════════════════════════

❓ Auth/headers ambiguous? → STOP and request clarification on blackboard
❓ Protected fields ambiguous? → STOP and align with contract/schema
❓ Validation or error shape unclear? → STOP and escalate mismatch
❓ Rate limits unclear? → use conservative defaults but report assumptions explicitly
❓ CORS uncertainty? → deny-by-default + explicit allowlist, and report required origin contract

NEVER: "I can't implement security without X"
INSTEAD: "Blocked by missing/ambiguous contract detail; clarification requested"
""",
            allowed_root=allowed_root,
            timeout=120
        )
        self.workspace = allowed_root


class TestEngineerAgent(GeneralAgent):
    """Custom agent for QA and testing"""
    
    def __init__(self, allowed_root=None):
        if allowed_root is None:
            allowed_root = WORKSPACE_DIR

        super().__init__(
            role="QA Engineer",
            role_description="Design comprehensive test suites and validate code quality across all layers",
            specific_instructions="""
═══════════════════════════════════════════════════════════════════════════════
QA ENGINEER WORKFLOW - GENERIC TESTING AND VALIDATION
═══════════════════════════════════════════════════════════════════════════════

PHASE 1: ANALYZE SYSTEM (Iteration 1-2)
  ├─ Read upstream components: Database schema, backend routes, frontend pages
  ├─ Map what was built by upstream agents
  ├─ Identify integration points and dependencies
  ├─ List external services (database, APIs, services)
  └─ Announce testing strategy to blackboard

PHASE 2: CREATE TEST PLAN (Iterations 3-5)
  ├─ test_plan.md - Document what will be tested
  ├─ Map backend endpoints/functions to test cases
  ├─ Map frontend components/pages to test cases  
  ├─ List database operations to test
  ├─ Identify external dependencies and mocking strategy
  └─ Document what will/won't pass

PHASE 3: BUILD TESTS (Iterations 6-12, 70% effort)
  ├─ tests/unit.test.js - Unit tests for core logic
  ├─ tests/integration.test.js - Integration tests between components
  ├─ tests/backend.test.js - Backend API and routes (if backend exists)
  ├─ tests/frontend.test.js - Frontend components (if frontend exists)
  ├─ tests/database.test.js - Database operations (if database schema exists)
  └─ tests/e2e.test.js - End-to-end workflows

PHASE 4: HANDLE MISSING COMPONENTS
  If database not running: ✅ keep unit tests isolated, but flag integration as BLOCKED
  If backend incomplete: ❌ do NOT hide with fake integration stubs; report CRITICAL mismatch
  If frontend missing: ✅ test available units and report integration gap explicitly
  If external services down: ✅ mock only external third-party dependencies, never core project contracts

PHASE 5: VALIDATION AND REPORTING (Final)
  ├─ Run all tests
  ├─ Document pass/fail status and reason
  ├─ Update_blackboard with test results and coverage
  └─ CRITICAL: Do NOT spend 10+ iterations fixing unfixable tests

═══════════════════════════════════════════════════════════════════════════════
TEST STRUCTURE PATTERNS - FOLLOW THESE
═══════════════════════════════════════════════════════════════════════════════

Unit Test Template:
  describe('Component/Function Name', () => {
    test('should do something specific', () => {
      const result = functionUnderTest(input);
      expect(result).toBe(expected);
    });
    test('should handle edge case', () => {
      const result = functionUnderTest(edgeInput);
      expect(result).toBe(edgeResult);
    });
  });

Backend API Test Template:
  describe('GET /api/endpoint', () => {
    test('should return success', async () => {
      const res = await request(app).get('/api/endpoint');
      expect(res.status).toBe(200);
      expect(res.body).toHaveProperty('data');
    });
  });

Frontend Component Test Template:
  describe('Component', () => {
    test('should render', () => {
      const { getByText } = render(<Component />);
      expect(getByText('expected text')).toBeInTheDocument();
    });
  });

Mocking Template:
  jest.mock('module-name', () => ({
    functionName: jest.fn(() => mockValue)
  }));

═══════════════════════════════════════════════════════════════════════════════
TEST COVERAGE GOALS
═══════════════════════════════════════════════════════════════════════════════

Core Functionality:
  ✅ Main business logic works
  ✅ Data models are correct
  ✅ API endpoints return expected responses
  ✅ Components render correctly

Integration:
  ✅ Components work together
  ✅ Frontend calls backend correctly
  ✅ Backend queries database correctly
  ✅ Authorization checks work

Error Cases:
  ✅ Invalid input is rejected
  ✅ Missing resources return 404
  ✅ Unauthorized access is blocked
  ✅ Edge cases are handled

═══════════════════════════════════════════════════════════════════════════════
OUTPUT FILES (relative paths in your workspace)
═══════════════════════════════════════════════════════════════════════════════

tests/
  ├─ test_plan.md - Testing strategy and coverage goals
  ├─ unit.test.js - Unit tests for individual functions
  ├─ integration.test.js - Integration tests
  ├─ backend.test.js - Backend API tests
  ├─ frontend.test.js - Frontend component tests
  ├─ database.test.js - Database operation tests
  └─ e2e.test.js - End-to-end workflow tests

package.json
  └─ scripts: add "test": "jest" if not present

jest.config.js
  └─ Jest configuration for test runner

═══════════════════════════════════════════════════════════════════════════════
SUCCESS CRITERIA FOR YOUR DELIVERABLES
═══════════════════════════════════════════════════════════════════════════════

✅ Test files created (even if they initially fail)
✅ Test structure follows best practices
✅ Tests cover critical functionality
✅ Mock external dependencies appropriately
✅ Tests run without crashing (even if they fail)
✅ Clear test names describing what's being tested
✅ Documentation about which tests require external services
✅ At least one real backend integration test exists (no mock backend)
✅ Contract conformance test asserts real endpoint/method/path alignment

═══════════════════════════════════════════════════════════════════════════════
WHEN TESTS FAIL - PIVOT STRATEGY
═══════════════════════════════════════════════════════════════════════════════

Tests fail with connection error? 
  → Keep unit tests isolated AND mark integration blocked (do not fake pass)

Tests fail with missing module?
  → Fix imports/dependencies or report exact blocker

Tests fail with missing endpoint/component?
  → Mark CRITICAL contract mismatch and fail verification

Tests fail 3+ times for same reason?
  → Escalate blocker with exact failing endpoint/test evidence

NEVER: "Tests are failing, I'm stuck"
INSTEAD: "Integration blocked by concrete contract/runtime mismatch; reported with evidence"

═══════════════════════════════════════════════════════════════════════════════
IF REQUIREMENTS UNCLEAR - FOLLOW THIS
═══════════════════════════════════════════════════════════════════════════════

❓ What should I test? → Test what upstream agents built
❓ How many tests? → At least 1 per major component/endpoint  
❓ What test framework? → Jest (works with Node.js and React)
❓ How to mock? → Only for third-party/external dependencies; never to hide backend/frontend contract drift
❓ Should all tests pass? → No, initially they fail (expected)

NEVER: "I can't test without X"
INSTEAD: "X missing blocks real integration; reporting CRITICAL issue"
""",
            allowed_root=allowed_root,
            timeout=120
        )
        self.workspace = allowed_root


class EnhancedAgentOrchestrator:
    """Orchestrates agents using GeneralAgent framework with cross-layer visibility"""
    
    def __init__(self, ledger_id: str):
        self.ledger_id = ledger_id
        self.ledger_path = os.path.join(WORKSPACE_DIR, f"ledger_{ledger_id}.json")
        self.blackboard = StructuredBlackboard()
        self.layer_blackboards = {}  # Per-layer blackboards
        
        # Load task ledger
        self.ledger = self._load_ledger()
        self._initialize_workspace_layout()
        
        # Build execution layers
        self.execution_layers = self._build_execution_layers()
        self._verify_director_structure()
        self.execution_layers = self._enforce_contract_first_execution_layers(self.execution_layers)
        
        # Track completed layers
        self.completed_workspaces = {}
        self._lsp_server_started = False
        self._rate_limit_lock = threading.Lock()
        self._global_pause_until = 0.0
        self.service_bus = ServiceBusCoordinator.from_env()

        # Option C: external verification policy (source of truth for completion)
        # Option 3 recommendation: centralized manifest requirements by role/language.
        self.role_verification_policy = {
          "api_designer": {
            "min_files": 2,
            "required_any": [
              ["api_contract.json", "contracts/api_contract.json"],
              ["README.md", "docs/api/README.md"]
            ],
            "manifest_any": []
          },
          "database_architect": {
            "min_files": 4,
            "required_any": [
              ["migrations/schema.sql"],
              ["migrations/seed_data.sql"],
              ["config/db_config.js"],
              ["config/db_setup.js"],
              ["README.md"]
            ],
            "manifest_any": ["package.json", "requirements.txt", "pyproject.toml"]
          },
          "security_engineer": {
            "min_files": 5,
            "required_any": [
              ["middleware/authMiddleware.js", "middleware/auth.js"],
              ["middleware/validation.js"],
              ["middleware/rateLimiter.js"],
              ["utils/encryption.js"],
              ["config/security.js"],
              ["README.md"]
            ],
            "manifest_any": ["package.json"]
          },
          "backend_engineer": {
            "min_files": 8,
            "required_any": [
              ["app.js"],
              ["config/database.js"],
              ["routes", "routes/catalog.js", "routes/items.js"],
              ["controllers", "controllers/catalogController.js", "controllers/itemsController.js"],
              ["README.md"]
            ],
            "manifest_any": ["package.json"]
          },
          "frontend_engineer": {
            "min_files": 7,
            "required_any": [
              ["src/App.jsx"],
              ["src/main.jsx", "src/index.js"],
              ["src/pages"],
              ["src/components"],
              ["src/utils/api.js", "src/utils/api.ts"],
              [".env.example"],
              ["README.md"]
            ],
            "manifest_any": ["package.json"]
          },
          "qa_engineer": {
            "min_files": 5,
            "required_any": [
              ["tests/test_plan.md"],
              ["jest.config.js"],
              ["tests/unit.test.js", "tests/integration.test.js", "tests/backend.test.js", "tests/frontend.test.js", "tests/database.test.js", "tests/e2e.test.js"],
              ["README.md"]
            ],
            "manifest_any": ["package.json"]
          }
        }

    def _initialize_workspace_layout(self):
        """Create director-declared production directories under workspace/."""
        layout = self.ledger.get("workspace_layout", {}) if isinstance(self.ledger, dict) else {}
        directories = layout.get("directories", []) if isinstance(layout.get("directories", []), list) else []
        role_roots = layout.get("role_output_roots", {}) if isinstance(layout.get("role_output_roots", {}), dict) else {}

        for d in directories:
            if isinstance(d, str) and d.strip():
                rel = self._normalize_workspace_rel(d)
                if rel:
                    os.makedirs(os.path.join(WORKSPACE_DIR, rel), exist_ok=True)

        for roots in role_roots.values():
            if isinstance(roots, str):
                roots = [roots]
            if not isinstance(roots, list):
                continue
            for root in roots:
                if isinstance(root, str) and root.strip():
                    rel = self._normalize_workspace_rel(root)
                    if rel:
                        os.makedirs(os.path.join(WORKSPACE_DIR, rel), exist_ok=True)

    def _get_agent_spec(self, role: str) -> Optional[Dict]:
        """Find agent spec by role from ledger."""
        agents = self.ledger.get("agent_specifications", {}).get("required_agents", [])
        for raw in agents:
            spec = self._normalize_agent_spec(raw)
            if spec and spec.get("role") == role:
                return spec
        return None

    def _normalize_agent_spec(self, raw_spec) -> Optional[Dict]:
        """Normalize required_agents entries to dict shape.

        Accepts:
        - "backend_engineer"
        - {"role": "backend_engineer", ...}
        - {"agent_name": "backend_engineer", ...}
        """
        if isinstance(raw_spec, str):
            role = raw_spec.strip()
            if not role:
                return None
            return {
                "role": role,
                "description": "",
                "instructions": ""
            }

        if isinstance(raw_spec, dict):
            role = raw_spec.get("role") or raw_spec.get("agent_name")
            if not role:
                return None
            normalized = dict(raw_spec)
            normalized["role"] = role
            normalized.setdefault("description", "")
            normalized.setdefault("instructions", "")
            return normalized

        return None

    def _execute_second_iteration(self):
        """Run review, then launch second iteration with issue-focused fixes."""
        print(f"\n{'='*70}")
        print("🔎 REVIEW PHASE: SCANNING GENERATED OUTPUT")
        print(f"{'='*70}")
        original_tracker = get_issues_tracker()
        iter2_issues_path = os.path.join(WORKSPACE_DIR, "issues_iteration2.json")
        iteration_tracker = IssuesTracker(file_path=iter2_issues_path)
        iteration_tracker.clear()
        set_issues_tracker(iteration_tracker)

        try:
            reviewer = ReviewAgent(WORKSPACE_DIR)
            new_issues = reviewer.review_and_record()

            if not new_issues:
                print("✅ Review agent found no issues. Skipping second iteration.")
                return

            print(f"⚠️ Review agent reported {len(new_issues)} issue(s). Starting second iteration...")

            # Create NEW shared blackboard for second iteration
            second_blackboard_path = os.path.join(WORKSPACE_DIR, "blackboard_iteration2.md")
            second_blackboard = StructuredBlackboard(path=second_blackboard_path)
            second_blackboard.clear()
            second_blackboard.post(
                "System",
                "Implementation plan",
                "Second iteration started. Agents must discuss assigned issues first, then implement fixes."
            )

            # Temporarily swap active blackboard to the second-iteration board
            original_blackboard = self.blackboard
            self.blackboard = second_blackboard

            try:
                issues_tracker = get_issues_tracker()
                open_issues = issues_tracker.get_open_issues()
                assigned_roles = sorted({i.get("assigned_to") for i in open_issues if i.get("assigned_to")})

                # Build agent specs only for roles that need to wake up
                fix_specs = []
                for role in assigned_roles:
                    spec = self._get_agent_spec(role)
                    if spec:
                        role_issues = issues_tracker.get_open_issues(assigned_to=role)
                        issue_list = "\n".join(
                            f"- [#{i['id']}] {i['component']}: {i['description']}"
                            for i in role_issues
                        )

                        # Mandatory discussion + fix instructions
                        patch_spec = dict(spec)
                        patch_spec["instructions"] = f"""{spec.get('instructions', '')}

      SECOND ITERATION - ISSUE FIX MODE (MANDATORY):
      1) Read your assigned issues from shared issues file.
      2) BEFORE coding, post your fix plan on the layer blackboard and discuss with relevant agents.
      3) Only after agreement, implement fixes.
      4) Update README.md with what was changed and why.

      Your assigned issues:
      {issue_list}
      """
                        fix_specs.append(patch_spec)

                if not fix_specs:
                    print("ℹ️ No valid agent specs matched assigned issues. Skipping second iteration execution.")
                    return

                print(f"\n{'='*70}")
                print("🔁 SECOND ITERATION: ISSUE RESOLUTION")
                print(f"{'='*70}")
                print(f"Waking up agents: {[s.get('role') for s in fix_specs]}\n")

                # Build logically ordered fix layers with maximal safe parallelization.
                fix_layers = self._build_second_iteration_layers(fix_specs)
                print(f"Planned fix layers: {[[a.get('role') for a in layer] for layer in fix_layers]}\n")

                for idx, layer_specs in enumerate(fix_layers):
                  layer_board_path = os.path.join(WORKSPACE_DIR, f"layer_iteration2_{idx + 1}_blackboard.md")
                  self.execute_layer(
                    idx,
                    layer_specs,
                    total_layers=len(fix_layers),
                    layer_blackboard_path=layer_board_path,
                    phase_label="FIX LAYER"
                  )

            finally:
                self.blackboard = original_blackboard

        finally:
            set_issues_tracker(original_tracker)

    def _build_issue_wake_specs(self) -> List[Dict]:
        """Build wake-up specs for roles currently assigned open issues."""
        issues_tracker = get_issues_tracker()
        open_issues = issues_tracker.get_open_issues()
        assigned_roles = sorted({
            str(i.get("assigned_to") or "").strip()
            for i in open_issues
            if str(i.get("assigned_to") or "").strip() and str(i.get("assigned_to") or "").strip().lower() != "unassigned"
        })

        wake_specs: List[Dict] = []
        for role in assigned_roles:
            spec = self._get_agent_spec(role)
            if not spec:
                continue
            role_issues = issues_tracker.get_open_issues(assigned_to=role)
            if not role_issues:
                continue

            issue_payload = json.dumps(role_issues, indent=2, ensure_ascii=False)
            patch_spec = dict(spec)
            patch_spec["instructions"] = f"""{spec.get('instructions', '')}

SECOND ITERATION - ISSUE FIX MODE (WAKE-UP):
You were woken up to resolve blocking issues assigned to your role.

MANDATORY STEPS:
1) Read assigned issues below and inspect implicated files.
2) Implement concrete fixes immediately.
3) Post what changed to the blackboard.
4) Ensure changes unblock dependent agents.
5) Output [READY_FOR_VERIFICATION] only after fixes are complete.

Assigned issues JSON:
{issue_payload}
"""
            wake_specs.append(patch_spec)

        return wake_specs

    def _resolve_issues_assigned_to_roles(self, roles: List[str], trigger: str) -> int:
        """Resolve all currently open issues assigned to roles after successful wake execution."""
        issues_tracker = get_issues_tracker()
        resolved_count = 0
        for role in roles:
            role_issues = issues_tracker.get_open_issues(assigned_to=role)
            for issue in role_issues:
                issue_id = issue.get("id")
                if issue_id is None:
                    continue
                resolved = issues_tracker.resolve_issue(
                    int(issue_id),
                    f"Auto-resolved after wake-up execution by {role} (trigger={trigger})"
                )
                if resolved:
                    resolved_count += 1
        return resolved_count

    def _run_issue_wake_cycle(self, trigger: str) -> int:
        """Run one or more issue-driven wake cycles for assigned roles."""
        max_cycles = max(1, int(os.getenv("ISSUE_WAKE_MAX_CYCLES", "2")))
        total_woken = 0

        for cycle in range(1, max_cycles + 1):
            wake_specs = self._build_issue_wake_specs()
            if not wake_specs:
                break

            wake_roles = [s.get("role") for s in wake_specs if s.get("role")]
            print(f"\n🔔 ISSUE WAKE CYCLE {cycle}/{max_cycles} (trigger={trigger})")
            print(f"Waking agents: {wake_roles}\n")

            wake_layers = self._build_second_iteration_layers(wake_specs)
            for idx, layer_specs in enumerate(wake_layers):
                layer_board_path = os.path.join(
                    WORKSPACE_DIR,
                    f"layer_issue_wake_{trigger}_{cycle}_{idx + 1}.md"
                )
                self.execute_layer(
                    idx,
                    layer_specs,
                    total_layers=len(wake_layers),
                    layer_blackboard_path=layer_board_path,
                    phase_label="ISSUE WAKE"
                )

            resolved = self._resolve_issues_assigned_to_roles(wake_roles, trigger=trigger)
            print(f"✅ Issue wake cycle resolved {resolved} issue(s)")
            total_woken += len(wake_roles)

        return total_woken

    def _is_rate_limit_error(self, error: Exception) -> bool:
        text = str(error).lower()
        return "too_many_requests" in text or "429" in text or "rate limit" in text

    def _infer_second_iteration_phase(self, spec: Dict) -> int:
      """Infer execution phase for second-iteration fixes using role/instruction semantics."""
      role = str(spec.get("role", "")).lower()
      text = " ".join([
        role,
        str(spec.get("description", "")),
        str(spec.get("instructions", ""))
      ]).lower()

      if any(k in text for k in ["qa", "test", "testing", "validation", "verify", "review"]):
        return 4
      if "frontend" in role or "ui" in role:
        return 3
      if any(k in text for k in ["devops", "deploy", "infra", "pipeline", "integration"]):
        return 2
      if any(k in text for k in ["backend", "api_designer", "api designer", "service", "controller", "route"]):
        return 1
      if any(k in text for k in ["database", "schema", "migration", "security", "architect"]):
        return 0
      return 1

    def _build_second_iteration_layers(self, fix_specs: List[Dict]) -> List[List[Dict]]:
      """Order fix agents into logical layers and group by inferred execution phase."""
      if not fix_specs:
        return []

      indexed = list(enumerate(fix_specs))
      indexed.sort(key=lambda t: (self._infer_second_iteration_phase(t[1]), t[0]))
      ordered_specs = [spec for _, spec in indexed]

      layers = []
      current_layer = []
      current_phase = None
      for spec in ordered_specs:
        phase = self._infer_second_iteration_phase(spec)
        if current_phase is None or phase == current_phase:
          current_layer.append(spec)
          current_phase = phase
        else:
          if current_layer:
            layers.append(current_layer)
          current_layer = [spec]
          current_phase = phase
      if current_layer:
        layers.append(current_layer)
      return layers

    def _schedule_global_pause(self, attempt_number: int) -> float:
        """Pause the whole system on rate limiting with exponential backoff."""
        base_delay = min(60, 2 ** max(1, attempt_number))
        jitter = random.uniform(0.0, 1.5)
        delay = min(60, base_delay + jitter)
        with self._rate_limit_lock:
            new_until = time.time() + delay
            if new_until > self._global_pause_until:
                self._global_pause_until = new_until
            remaining = max(0, self._global_pause_until - time.time())
        return remaining

    def _wait_if_globally_paused(self):
        while True:
            with self._rate_limit_lock:
                wait_for = self._global_pause_until - time.time()
            if wait_for <= 0:
                return
            print(f"⏸️ Global pause active due to rate limiting. Waiting {wait_for:.1f}s...")
            time.sleep(min(wait_for, 2.0))
    
    def _load_ledger(self) -> Dict:
        """Load task ledger from file"""
        if not os.path.exists(self.ledger_path):
            raise FileNotFoundError(f"Ledger not found: {self.ledger_path}")
        
        with open(self.ledger_path, 'r') as f:
            return json.load(f)
    
    def _build_execution_layers(self) -> List[List[Dict]]:
      """Parse task ledger and build execution layers.

      Preferred format: agent_specifications.layers = [["role1", "role2"], ...]
      Legacy fallback: build from agent_dependencies DAG.
      """
      spec = self.ledger.get("agent_specifications", {})
      raw_agents = spec.get("required_agents", [])
      agents = [self._normalize_agent_spec(a) for a in raw_agents]
      agents = [a for a in agents if a and a.get("role")]
      if not agents:
        raise ValueError("No agents defined in task ledger")

      agent_map = {a.get("role"): a for a in agents if a.get("role")}
      explicit_layers = spec.get("layers", []) or []

      if explicit_layers:
        layers = []
        seen = set()
        for idx, layer_entry in enumerate(explicit_layers, 1):
          # Accept both:
          # 1) ["frontend_engineer", "backend_engineer"]
          # 2) {"layer_name": "Backend", "agents": [{"role": "backend_engineer"}, ...]}
          if isinstance(layer_entry, list):
            layer_roles = layer_entry
          elif isinstance(layer_entry, dict):
            layer_agents = layer_entry.get("agents", [])
            if not isinstance(layer_agents, list):
              raise ValueError(f"Invalid layer #{idx}: 'agents' must be a list")
            layer_roles = []
            for agent_ref in layer_agents:
              if isinstance(agent_ref, str):
                layer_roles.append(agent_ref)
              elif isinstance(agent_ref, dict):
                role = agent_ref.get("role")
                if not role:
                  raise ValueError(f"Invalid layer #{idx}: each agent object must include 'role'")
                layer_roles.append(role)
              else:
                raise ValueError(f"Invalid layer #{idx}: unsupported agent entry type")
          else:
            raise ValueError(f"Invalid layer #{idx}: must be a list or an object with 'agents'")

          if len(layer_roles) == 0:
            raise ValueError(f"Invalid layer #{idx}: must contain at least one agent")
          layer_specs = []
          for role in layer_roles:
            if role not in agent_map:
              raise ValueError(f"Layer #{idx} references unknown role: {role}")
            if role in seen:
              raise ValueError(f"Role appears in multiple layers: {role}")
            seen.add(role)
            layer_specs.append(agent_map[role])
          layers.append(layer_specs)

        missing_roles = set(agent_map.keys()) - seen
        if missing_roles:
          raise ValueError(f"Layers missing roles: {sorted(missing_roles)}")
        return layers

      # Legacy dependency fallback
      dependencies = spec.get("agent_dependencies", {})
      layers = []
      remaining = set(agent_map.keys())
      visited = set()

      while remaining:
        ready = []
        for role in remaining:
          agent_deps = dependencies.get(role, [])
          if all(dep in visited for dep in agent_deps):
            ready.append(agent_map[role])

        if not ready:
          unresolved = sorted(list(remaining))
          raise ValueError(
            "Cycle or unresolved dependency detected in agent_dependencies. "
            f"Use agent_specifications.layers instead. Remaining: {unresolved}"
          )

        # Minimize total layers: execute all currently-ready roles in parallel.
        layers.append(ready)
        current_roles = {a.get("role") for a in ready}
        remaining -= current_roles
        visited.update(current_roles)

      return layers

    def _verify_director_structure(self) -> None:
      """Verify director-provided layering follows contract-first structure when standard roles exist."""
      spec = self.ledger.get("agent_specifications", {}) if isinstance(self.ledger, dict) else {}
      explicit_layers = spec.get("layers", []) or []
      if not explicit_layers:
        return

      role_to_layer = {}
      for idx, layer_entry in enumerate(explicit_layers):
        if isinstance(layer_entry, list):
          roles = [r for r in layer_entry if isinstance(r, str)]
        elif isinstance(layer_entry, dict):
          roles = []
          for a in (layer_entry.get("agents", []) or []):
            if isinstance(a, str):
              roles.append(a)
            elif isinstance(a, dict) and a.get("role"):
              roles.append(a.get("role"))
        else:
          continue
        for r in roles:
          role_to_layer[r] = idx

      expected_order = ["api_designer", "database_architect", "security_engineer", "backend_engineer", "frontend_engineer", "qa_engineer"]
      present = [r for r in expected_order if r in role_to_layer]
      for i in range(len(present) - 1):
        left = present[i]
        right = present[i + 1]
        if role_to_layer[left] > role_to_layer[right]:
          raise RuntimeError(
            "CRITICAL: Director layer order violates contract-first structure. "
            f"Expected {left} to execute before {right}."
          )

    def _load_contract_context(self) -> Dict:
      """Load full contract as first-class context payload."""
      contract_path = os.path.join(WORKSPACE_DIR, "contracts", "api_contract.json")
      with open(contract_path, "r", encoding="utf-8", errors="ignore") as f:
        raw = f.read()

      parsed = json.loads(raw)
      route_map = self._extract_contract_route_map(parsed)
      checksum = hashlib.sha256(raw.encode("utf-8")).hexdigest()
      return {
        "path": "contracts/api_contract.json",
        "checksum_sha256": checksum,
        "endpoint_count": len(route_map),
        "content": raw,
      }

    def _normalize_contract_path(self, path: str) -> str:
      """Normalize API path and convert OpenAPI path params ({id}) to :id."""
      p = self._normalize_api_path(path)
      p = re.sub(r"\{\s*([^}]+?)\s*\}", lambda m: f":{m.group(1).strip()}", p)
      return p

    def _extract_contract_route_map(self, data: Dict) -> Dict:
      """Extract {'METHOD /path': meta} from either endpoints[] or OpenAPI paths{}."""
      route_map = {}
      if not isinstance(data, dict):
        return route_map

      # Legacy/custom contract shape: endpoints: [{"route": "GET /items"}, ...]
      endpoints = data.get("endpoints", [])
      if isinstance(endpoints, list):
        for ep in endpoints:
          route = ""
          if isinstance(ep, dict):
            route = str(ep.get("route", "")).strip()
          if not route or " " not in route:
            continue
          method, raw_path = route.split(" ", 1)
          key = f"{method.upper()} {self._normalize_contract_path(raw_path)}"
          route_map[key] = ep

      # OpenAPI shape: paths: {"/items/{id}": {"get": {...}}}
      paths = data.get("paths", {})
      if isinstance(paths, dict):
        allowed_methods = {"get", "post", "put", "patch", "delete", "head", "options"}
        for raw_path, path_item in paths.items():
          if not isinstance(path_item, dict):
            continue
          for method, op in path_item.items():
            if str(method).lower() not in allowed_methods:
              continue
            key = f"{str(method).upper()} {self._normalize_contract_path(str(raw_path))}"
            if key not in route_map:
              route_map[key] = op if isinstance(op, dict) else {"route": key}

      return route_map

    def _enforce_contract_first_execution_layers(self, layers: List[List[Dict]]) -> List[List[Dict]]:
      """Force contract-first execution order when standard roles are present."""
      flat_specs = []
      for layer in layers or []:
        for spec in layer or []:
          if isinstance(spec, dict) and spec.get("role"):
            flat_specs.append(spec)

      if not flat_specs:
        return layers

      by_role = {s.get("role"): s for s in flat_specs}
      ordered_layers = []
      consumed = set()

      phase_roles = [
        ["api_designer"],
        ["database_architect", "security_engineer"],
        ["backend_engineer", "frontend_engineer"],
        ["qa_engineer"],
      ]

      for phase in phase_roles:
        phase_specs = []
        for role in phase:
          if role in by_role:
            phase_specs.append(by_role[role])
            consumed.add(role)
        if phase_specs:
          ordered_layers.append(phase_specs)

      remaining = [s for s in flat_specs if s.get("role") not in consumed]
      if remaining:
        ordered_layers.append(remaining)

      return ordered_layers if ordered_layers else layers

    def _require_global_contract(self) -> None:
      """Global contract existence/validity gate before executing layers."""
      roles_present = {
        (spec.get("role") or "")
        for layer in (self.execution_layers or [])
        for spec in (layer or [])
        if isinstance(spec, dict)
      }

      contract_consumers = {"database_architect", "backend_engineer", "frontend_engineer", "qa_engineer"}
      if not (roles_present & contract_consumers):
        return

      if "api_designer" not in roles_present:
        raise RuntimeError("CRITICAL: api_designer role is required for contract-first workflow")

      contract_path = os.path.join(WORKSPACE_DIR, "contracts", "api_contract.json")
      if not os.path.exists(contract_path):
        # Allow first run when api_designer is present; it must generate the contract in layer 1.
        if "api_designer" in roles_present:
          return
        raise RuntimeError("CRITICAL: API contract missing at workspace/contracts/api_contract.json")

      try:
        with open(contract_path, "r", encoding="utf-8", errors="ignore") as f:
          payload = json.load(f)
        routes = self._extract_contract_route_map(payload)
        if len(routes) == 0:
          raise ValueError("contract must define routes via non-empty endpoints[] or paths{}")
      except Exception as e:
        raise RuntimeError(f"CRITICAL: API contract invalid: {str(e)}")
    
    def _get_agent_workspace(self, role: str) -> str:
      """Get primary role output root under workspace (production-style layout)."""
      roots = self._get_role_output_roots(role)
      primary = roots[0] if roots else role.replace(" ", "_").lower()
      workspace = os.path.join(WORKSPACE_DIR, primary)
      os.makedirs(workspace, exist_ok=True)
      return workspace

    def _normalize_workspace_rel(self, path: str) -> str:
      p = str(path or "").replace("\\", "/").strip()
      if p.startswith("./workspace/"):
        p = p[len("./workspace/"):]
      elif p.startswith("workspace/"):
        p = p[len("workspace/"):]
      elif p.startswith("./"):
        p = p[2:]
      return p.strip("/")

    def _get_role_output_roots(self, role: str) -> List[str]:
      """Resolve production output roots for a role from ledger workspace_layout."""
      role_key = (role or "").strip().lower().replace(" ", "_")
      layout = self.ledger.get("workspace_layout", {}) if isinstance(self.ledger, dict) else {}
      role_map = layout.get("role_output_roots", {}) if isinstance(layout.get("role_output_roots", {}), dict) else {}
      raw_roots = role_map.get(role_key, [])
      if isinstance(raw_roots, str):
        raw_roots = [raw_roots]

      roots = [self._normalize_workspace_rel(r) for r in (raw_roots or []) if self._normalize_workspace_rel(r)]
      if role_key == "api_designer":
        # API contract is single source of truth under contracts/.
        if "contracts" not in roots:
          roots.insert(0, "contracts")
        if "docs/api" not in roots:
          roots.append("docs/api")
      if roots:
        return roots
      return [role_key]

    def _list_role_generated_files(self, role: str) -> List[str]:
      """List files generated under this role's mapped output roots."""
      files = []
      seen = set()
      for root in self._get_role_output_roots(role):
        abs_root = os.path.join(WORKSPACE_DIR, root)
        for rel in self._list_generated_files(abs_root):
          full_rel = f"{root}/{rel}" if rel else root
          if full_rel not in seen:
            seen.add(full_rel)
            files.append(full_rel)
      return sorted(files)
    
    def _build_cross_layer_context(self, role: str) -> Dict:
        """
        Build context for agent including:
        - Project requirements
        - Technology stack
        - Output from previous agents
        """
        context = {
            "project_name": self.ledger.get("project_name"),
            "project_description": self.ledger.get("project_description"),
            "requirements": self.ledger.get("functional_requirements", []),
            "tech_stack": self.ledger.get("technology_stack", {}),
            "previous_outputs": {},
            "required_upstream_roles": self._required_upstream_roles(role),
          "workspace_layout": self.ledger.get("workspace_layout", {}),
        }
        
        # Include actual files from completed layers
        for agent_role, workspace in self.completed_workspaces.items():
            context["previous_outputs"][agent_role] = {
                "workspace": workspace,
            "files": self._list_role_generated_files(agent_role)
            }

        role_norm = (role or "").strip().lower().replace(" ", "_")
        if role_norm in {"database_architect", "backend_engineer", "frontend_engineer"}:
          context["api_contract"] = self._load_contract_context()
          context["contract_required"] = True
        
        return context

    def _required_upstream_roles(self, role: str) -> List[str]:
        role_norm = (role or "").strip().lower()
        mapping = {
      "database_architect": ["api_designer"],
        "backend_engineer": ["database_architect", "security_engineer", "api_designer"],
        "frontend_engineer": ["api_designer", "backend_engineer"],
            "qa_engineer": ["database_architect", "security_engineer", "backend_engineer", "frontend_engineer"],
            "security_engineer": ["database_architect"],
        }
        return mapping.get(role_norm, [])

    def _enforce_role_prerequisites(self, role: str, current_layer_roles: Optional[List[str]] = None) -> None:
      """Hard gate for contract-first orchestration and upstream dependencies."""
      role_norm = (role or "").strip().lower().replace(" ", "_")
      required = self._required_upstream_roles(role_norm)
      coexecuting_roles = {
        str(r or "").strip().lower().replace(" ", "_")
        for r in (current_layer_roles or [])
      }
      missing_upstream = [
        r for r in required
        if r not in self.completed_workspaces and r not in coexecuting_roles
      ]
      if missing_upstream:
        raise RuntimeError(
          f"CRITICAL: {role_norm} cannot start. Missing completed upstream roles: {', '.join(missing_upstream)}"
        )

      contract_required_roles = {"database_architect", "backend_engineer", "frontend_engineer", "qa_engineer"}
      if role_norm in contract_required_roles:
        contract_path = os.path.join(WORKSPACE_DIR, "contracts", "api_contract.json")
        if not os.path.exists(contract_path):
          raise RuntimeError(
            "CRITICAL: contracts/api_contract.json is required before this role can execute"
          )
        try:
          with open(contract_path, "r", encoding="utf-8", errors="ignore") as f:
            contract = json.load(f)
          routes = self._extract_contract_route_map(contract)
          if len(routes) == 0:
            raise ValueError("missing routes (expected endpoints[] or paths{})")
        except Exception as e:
          raise RuntimeError(
            f"CRITICAL: contracts/api_contract.json is invalid and cannot be used as source of truth: {str(e)}"
          )
    
    def _list_generated_files(self, workspace: str) -> List[str]:
        """List all generated files in a workspace"""
        files = []
        if os.path.exists(workspace):
            for root, dirs, filenames in os.walk(workspace):
                dirs[:] = [
                    d for d in dirs
                    if d not in {"node_modules", ".git", "dist", "build", "coverage", "__pycache__"}
                ]
                for filename in filenames:
                    if filename.endswith(".pyc"):
                        continue
                    filepath = os.path.join(root, filename)
                    relpath = os.path.relpath(filepath, workspace)
                    files.append(relpath)
        return files

    def _build_retry_workspace_snapshot(self, role: str, workspace: str, max_files: int = 30) -> str:
      """Build compact retry context so reruns continue from existing artifacts."""
      files = sorted(self._list_role_generated_files(role))
      roots = self._get_role_output_roots(role)
      lines = [
        f"Workspace snapshot for '{role}':",
        f"- Output roots: {', '.join(roots)}",
        f"- Existing files: {len(files)}"
      ]

      if files:
        for rel in files[:max_files]:
          lines.append(f"  - {rel}")
        if len(files) > max_files:
          lines.append(f"  - ... (+{len(files) - max_files} more files)")
      else:
        lines.append("  - (no files found yet)")

      notebook_path = os.path.join(NOTEBOOKS_DIR, f"{role}.md")
      if os.path.exists(notebook_path):
        try:
          with open(notebook_path, "r", encoding="utf-8", errors="ignore") as f:
            notebook_tail = f.read()[-1500:]
          if notebook_tail.strip():
            lines.append("- Notebook tail (most recent context):")
            lines.append(notebook_tail)
        except Exception:
          pass

      return "\n".join(lines)

    def _matches_any_path(self, generated_files: List[str], candidates: List[str]) -> bool:
        """Return True if any candidate path (file or folder prefix) exists in generated files."""
        normalized = [f.replace("\\", "/") for f in generated_files]
        for candidate in candidates:
            c = candidate.replace("\\", "/").rstrip("/")
            # Exact file
            if c in normalized:
                return True
            # Suffix file/folder under mapped production root
            if any(f.endswith("/" + c) for f in normalized):
                return True
            # Folder/prefix existence
            if any(f.startswith(c + "/") for f in normalized):
                return True
            # Folder/prefix existence under mapped production root
            if any(("/" + c + "/") in ("/" + f) for f in normalized):
                return True
        return False

    def _verify_agent_deliverables(self, role: str, workspace: str) -> Dict:
        """External verifier for agent completion (Option C source-of-truth)."""
        role_key = role.lower().replace(" ", "_")
        files = self._list_role_generated_files(role)
        policy = self.role_verification_policy.get(role_key, {
            "min_files": 1,
            "required_any": [],
            "manifest_any": ["package.json", "requirements.txt", "pyproject.toml"]
        })

        missing = []
        if len(files) < policy["min_files"]:
            missing.append(f"minimum files not met: {len(files)}/{policy['min_files']}")

        for req_group in policy.get("required_any", []):
            if not self._matches_any_path(files, req_group):
                missing.append(f"missing one of: {', '.join(req_group)}")

        if policy.get("manifest_any") and not self._matches_any_path(files, policy["manifest_any"]):
            missing.append(f"missing dependency manifest (one of: {', '.join(policy['manifest_any'])})")

        contract_check = self._verify_contract_alignment(role_key, workspace)
        if not contract_check["ok"]:
          missing.extend(contract_check.get("missing", []))

        # Quality gate: reject obvious placeholder scaffolding for core app roles.
        if role_key in {"backend_engineer", "frontend_engineer"}:
            placeholder_hits = self._find_placeholder_artifacts(workspace)
            if placeholder_hits:
                preview = ", ".join(placeholder_hits[:8])
                missing.append(
                    "placeholder scaffolding detected in implementation files: "
                    f"{preview}"
                )

        return {
            "ok": len(missing) == 0,
            "files_count": len(files),
            "files": files,
            "missing": missing
        }

    def _find_placeholder_artifacts(self, workspace: str) -> List[str]:
        """Return relative file paths that contain clear placeholder/stub markers."""
        markers = [
          r"\bplaceholder\s+(?:code|logic|implementation|route|stub|handler|response|component|file)\b",
          r"\b(?:todo|fixme)\s*:",
            r"\bstub\b",
            r"fill in actual",
            r"implement(?:ation)?\s+later",
            r"\bsimplified\b",
            r"\bdummy\b",
            r"mock response"
        ]
        marker_re = re.compile("|".join(markers), re.IGNORECASE)
        hits = []
        for root, dirs, files in os.walk(workspace):
            dirs[:] = [d for d in dirs if d not in {"node_modules", ".git", "dist", "build", "coverage", "ml"}]
            for name in files:
                if not name.endswith((".js", ".jsx", ".ts", ".tsx", ".py")):
                    continue
                rel = os.path.relpath(os.path.join(root, name), workspace).replace("\\", "/")
                # Keep docs out of this gate; focus on executable code files.
                if rel.lower().startswith("docs/") or rel.lower().endswith("readme.md"):
                    continue
                try:
                    with open(os.path.join(root, name), "r", encoding="utf-8", errors="ignore") as f:
                        src = f.read()
                except Exception:
                    continue
                if marker_re.search(src):
                    hits.append(rel)
        return sorted(set(hits))

    def _load_package_scripts(self, workspace: str) -> Dict[str, str]:
        package_json = os.path.join(workspace, "package.json")
        data = self._read_json_file(package_json)
        if not isinstance(data, dict):
            return {}
        scripts = data.get("scripts", {})
        if not isinstance(scripts, dict):
            return {}
        return {str(k): str(v) for k, v in scripts.items()}

    def _run_npm_script(self, workspace: str, script_name: str, timeout_seconds: int, long_running_ok: bool) -> Dict:
      def _to_text(value) -> str:
        if value is None:
          return ""
        if isinstance(value, bytes):
          return value.decode("utf-8", errors="ignore")
        return str(value)

      cmd = ["npm", "run", script_name]
      try:
        completed = subprocess.run(
          cmd,
          cwd=workspace,
          capture_output=True,
          text=True,
          timeout=max(5, int(timeout_seconds)),
        )
        out = _to_text(completed.stdout) + "\n" + _to_text(completed.stderr)
        if completed.returncode == 0:
          return {"ok": True, "message": f"npm run {script_name} succeeded", "output": out[-4000:]}
        return {
          "ok": False,
          "message": f"npm run {script_name} failed with exit code {completed.returncode}",
          "output": out[-4000:],
        }
      except subprocess.TimeoutExpired as te:
        if long_running_ok:
          out = _to_text(te.stdout) + "\n" + _to_text(te.stderr)
          return {
            "ok": True,
            "message": f"npm run {script_name} appears to be running (timeout reached)",
            "output": out[-4000:],
          }
        out = _to_text(te.stdout) + "\n" + _to_text(te.stderr)
        return {
          "ok": False,
          "message": f"npm run {script_name} timed out",
          "output": out[-4000:],
        }
      except FileNotFoundError:
        return {"ok": False, "message": "npm executable not found", "output": ""}
      except Exception as e:
        return {"ok": False, "message": f"failed to run npm script: {str(e)}", "output": ""}

    def _run_post_verification_runtime_check(self, role_key: str, workspace: str) -> Dict:
        """Run runtime smoke checks after deliverable verification succeeds."""
        if role_key not in {"backend_engineer", "frontend_engineer"}:
            return {"ok": True, "checks": []}

        scripts = self._load_package_scripts(workspace)
        if not scripts:
            return {"ok": False, "error": "runtime smoke check: package.json scripts not found", "checks": []}

        checks = []

        if role_key == "frontend_engineer":
            if "build" in scripts:
                build = self._run_npm_script(
                    workspace,
                    "build",
                    timeout_seconds=FRONTEND_BUILD_TIMEOUT_SECONDS,
                    long_running_ok=False,
                )
                checks.append({"script": "build", **build})
                if not build.get("ok"):
                    return {
                        "ok": False,
                        "error": build.get("message", "frontend build failed"),
                        "checks": checks,
                        "output": build.get("output", ""),
                    }

            dev_like = "dev" if "dev" in scripts else ("start" if "start" in scripts else None)
            if dev_like:
                run_out = self._run_npm_script(
                    workspace,
                    dev_like,
                    timeout_seconds=RUNTIME_SMOKE_TIMEOUT_SECONDS,
                    long_running_ok=True,
                )
                checks.append({"script": dev_like, **run_out})
                if not run_out.get("ok"):
                    return {
                        "ok": False,
                        "error": run_out.get("message", "frontend runtime smoke failed"),
                        "checks": checks,
                        "output": run_out.get("output", ""),
                    }
            return {"ok": True, "checks": checks}

        # backend_engineer
        run_like = "dev" if "dev" in scripts else ("start" if "start" in scripts else None)
        if not run_like:
            return {
                "ok": False,
                "error": "runtime smoke check: backend package.json missing dev/start script",
                "checks": checks,
            }

        run_out = self._run_npm_script(
            workspace,
            run_like,
            timeout_seconds=RUNTIME_SMOKE_TIMEOUT_SECONDS,
            long_running_ok=True,
        )
        checks.append({"script": run_like, **run_out})
        if not run_out.get("ok"):
            return {
                "ok": False,
                "error": run_out.get("message", "backend runtime smoke failed"),
                "checks": checks,
                "output": run_out.get("output", ""),
            }

        return {"ok": True, "checks": checks}

    def _normalize_api_path(self, path: str) -> str:
        p = (path or "").strip()
        if not p:
            return "/"
        if not p.startswith("/"):
            p = "/" + p
        p = re.sub(r"/+", "/", p)
        if len(p) > 1 and p.endswith("/"):
            p = p[:-1]
        return p

    def _normalize_template_path(self, path: str) -> str:
        p = self._normalize_api_path(path)
        # Convert template placeholders like ${order_id} to :order_id for contract comparison.
        p = re.sub(r"\$\{\s*([^}]+?)\s*\}", lambda m: f":{m.group(1).strip()}", p)
        return p

    def _read_json_file(self, abs_path: str) -> Optional[Dict]:
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                return json.load(f)
        except Exception:
            return None

    def _load_contract_routes(self) -> Dict:
      """Load contract routes as {'METHOD /path': meta} map from contracts/api_contract.json."""
      contract_path = os.path.join(WORKSPACE_DIR, "contracts", "api_contract.json")
      data = self._read_json_file(contract_path)
      if not isinstance(data, dict):
        return {"ok": False, "routes": {}, "error": "contracts/api_contract.json missing or invalid JSON"}

      route_map = self._extract_contract_route_map(data)
      if not route_map:
        return {
          "ok": False,
          "routes": {},
          "error": "contracts/api_contract.json has no usable routes (expected endpoints[] or paths{})"
        }
      return {"ok": True, "routes": route_map}

    def _auto_heal_empty_contract(self) -> bool:
      """If api_contract exists but has no usable routes, write a minimal valid fallback contract."""
      contract_path = os.path.join(WORKSPACE_DIR, "contracts", "api_contract.json")
      if not os.path.exists(contract_path):
        return False

      data = self._read_json_file(contract_path)
      if not isinstance(data, dict):
        return False

      current_routes = self._extract_contract_route_map(data)
      if current_routes:
        return False

      os.makedirs(os.path.dirname(contract_path), exist_ok=True)
      fallback_contract = {
        "project": self.ledger.get("project_name") or self.ledger.get("project_id") or "project",
        "version": "1.0.0",
        "endpoints": [
          {"method": "GET", "path": "/api/health", "description": "Health check"},
          {"method": "GET", "path": "/api/items", "description": "List items"},
          {"method": "POST", "path": "/api/items", "description": "Create item"},
          {"method": "GET", "path": "/api/items/:id", "description": "Get item by id"},
          {"method": "PUT", "path": "/api/items/:id", "description": "Update item by id"},
          {"method": "DELETE", "path": "/api/items/:id", "description": "Delete item by id"}
        ],
        "_generated_by": "orchestrator_contract_heal"
      }
      with open(contract_path, "w", encoding="utf-8") as f:
        json.dump(fallback_contract, f, indent=2)
      print("⚠️ API contract had no routes; wrote fallback contract at workspace/contracts/api_contract.json")
      return True

    def _collect_backend_routes(self, workspace: str) -> Dict:
        """Collect effective backend routes as {'METHOD /path'} from app mounts + route files."""
        app_js = os.path.join(workspace, "app.js")
        if not os.path.exists(app_js):
            return {"ok": False, "routes": set(), "error": "backend app.js not found"}

        try:
            with open(app_js, "r", encoding="utf-8", errors="ignore") as f:
                app_src = f.read()
        except Exception as e:
            return {"ok": False, "routes": set(), "error": f"failed reading backend app.js: {str(e)}"}

        var_to_route_file = {}
        require_re = re.compile(r"(?:const|let|var)\s+(\w+)\s*=\s*require\(['\"]\./routes/([^'\"]+)['\"]\)")
        for m in require_re.finditer(app_src):
            var_to_route_file[m.group(1)] = m.group(2)

        mount_re = re.compile(r"app\.use\(\s*['\"]([^'\"]+)['\"]\s*,\s*(\w+)\s*\)")
        mount_inline_require_re = re.compile(
          r"app\.use\(\s*['\"]([^'\"]+)['\"]\s*,\s*require\(\s*['\"]\./routes/([^'\"]+)['\"]\s*\)\s*\)"
        )
        mount_inline_controller_re = re.compile(
          r"app\.use\(\s*['\"]([^'\"]+)['\"]\s*,\s*require\(\s*['\"]\./controllers/[^'\"]+['\"]\s*\)"
        )
        mount_no_base_re = re.compile(r"app\.use\(\s*(\w+)\s*\)")
        mount_no_base_inline_require_re = re.compile(
          r"app\.use\(\s*require\(\s*['\"]\./routes/([^'\"]+)['\"]\s*\)\s*\)"
        )
        mounted = []
        methodless_paths = set()
        for m in mount_re.finditer(app_src):
          mount_base = self._normalize_api_path(m.group(1))
          var_name = m.group(2)
          route_rel = var_to_route_file.get(var_name)
          if route_rel:
            mounted.append((mount_base, route_rel))
          else:
            # app.use('/path', handlerFn) style; method unknown from static parsing.
            methodless_paths.add(mount_base)

        # Support direct inline mounts like: app.use('/auth', require('./routes/auth'))
        for m in mount_inline_require_re.finditer(app_src):
          mount_base = self._normalize_api_path(m.group(1))
          route_rel = m.group(2)
          if route_rel:
            mounted.append((mount_base, route_rel))

        # Support inline controller handler mounts such as
        # app.use('/checkout', require('./controllers/checkout').checkout)
        for m in mount_inline_controller_re.finditer(app_src):
          methodless_paths.add(self._normalize_api_path(m.group(1)))

        # Also support app.use(routerVar) where full paths are declared in route files.
        for m in mount_no_base_re.finditer(app_src):
          var_name = m.group(1)
          route_rel = var_to_route_file.get(var_name)
          if route_rel:
            mounted.append(("", route_rel))

        # Support direct inline mounts without explicit base:
        # app.use(require('./routes/someRouter'))
        for m in mount_no_base_inline_require_re.finditer(app_src):
          route_rel = m.group(1)
          if route_rel:
            mounted.append(("", route_rel))

        # Fallback: if mounts were not detected, scan all files under routes/.
        routes_dir = os.path.join(workspace, "routes")
        if not mounted and os.path.isdir(routes_dir):
          for name in os.listdir(routes_dir):
            if name.endswith(".js"):
              mounted.append(("", name[:-3]))

        routes = set()
        app_route_decl_re = re.compile(r"app\.(get|post|put|patch|delete)\(\s*['\"]([^'\"]+)['\"]")
        for rm in app_route_decl_re.finditer(app_src):
          method = rm.group(1).upper()
          full_path = self._normalize_api_path(rm.group(2))
          routes.add(f"{method} {full_path}")

        route_decl_re = re.compile(r"router\.(get|post|put|patch|delete)\(\s*['\"]([^'\"]+)['\"]")
        for mount_base, route_rel in mounted:
            abs_route_file = os.path.join(workspace, "routes", route_rel)
            if not abs_route_file.endswith(".js"):
                abs_route_file = abs_route_file + ".js"
            if not os.path.exists(abs_route_file):
                continue
            try:
                with open(abs_route_file, "r", encoding="utf-8", errors="ignore") as f:
                    route_src = f.read()
            except Exception:
                continue

            for rm in route_decl_re.finditer(route_src):
                method = rm.group(1).upper()
                sub_path = rm.group(2)
                full_path = self._normalize_api_path(f"{mount_base}/{sub_path.lstrip('/')}")
                routes.add(f"{method} {full_path}")

        return {"ok": True, "routes": routes, "methodless_paths": methodless_paths}

    def _collect_frontend_api_calls(self, workspace: str) -> Dict:
        """Collect frontend API calls from src/utils/api.js as {'METHOD /path'} set."""
        api_util = os.path.join(workspace, "src", "utils", "api.js")
        if not os.path.exists(api_util):
            return {"ok": False, "routes": set(), "error": "frontend src/utils/api.js not found"}

        try:
            with open(api_util, "r", encoding="utf-8", errors="ignore") as f:
                src = f.read()
        except Exception as e:
            return {"ok": False, "routes": set(), "error": f"failed reading frontend api util: {str(e)}"}

        calls = set()
        # Support common wrappers plus native fetch()
        fetch_fn = r"(?:apiFetch|handleFetch|fetchJson|request|http|fetch)"
        two_arg_re = re.compile(
            rf"{fetch_fn}\(\s*([`][^`]+[`]|'[^']+'|\"[^\"]+\")\s*,\s*\{{([\s\S]*?)\}}\s*\)",
            re.MULTILINE
        )
        one_arg_re = re.compile(rf"{fetch_fn}\(\s*([`][^`]+[`]|'[^']+'|\"[^\"]+\")\s*\)")
        axios_re = re.compile(
          r"\b(?:apiClient|axios)\.(get|post|put|patch|delete)\(\s*([`][^`]+[`]|'[^']+'|\"[^\"]+\")",
          re.MULTILINE
        )

        def _strip_quotes(s: str) -> str:
            t = (s or "").strip()
            if len(t) >= 2 and ((t[0] == "'" and t[-1] == "'") or (t[0] == '"' and t[-1] == '"') or (t[0] == "`" and t[-1] == "`")):
                return t[1:-1]
            return t

        def _extract_api_path(raw: str) -> str:
            t = (raw or "").strip()
            t = t.replace("${BASE_URL}", "").replace("${baseUrl}", "")
            t = re.sub(r"https?://[^/]+", "", t)
            # Preserve path-template segments like /${id} as /:param.
            t = re.sub(r"/\$\{[^}]+\}", "/:param", t)
            # Remove remaining template expressions (typically query builders like ${qp ? ...}).
            t = re.sub(r"\$\{[^}]+\}", "", t)

            idx = t.find("/api/")
            if idx >= 0:
                t = t[idx:]
            elif t.startswith("/api"):
                t = t
            elif t.startswith("/"):
                t = t
            else:
                slash_idx = t.find("/")
                t = t[slash_idx:] if slash_idx >= 0 else t

            t = t.split("?", 1)[0]
            return self._normalize_template_path(t)

        for m in two_arg_re.finditer(src):
            raw_endpoint = _strip_quotes(m.group(1))
            opts = m.group(2)
            mm = re.search(r"method\s*:\s*['\"]([A-Za-z]+)['\"]", opts)
            method = (mm.group(1).upper() if mm else "GET")
            path = _extract_api_path(raw_endpoint)
            calls.add(f"{method} {path}")

        for m in one_arg_re.finditer(src):
            raw_endpoint = _strip_quotes(m.group(1))
            path = _extract_api_path(raw_endpoint)
            calls.add(f"GET {path}")

        # Axios pattern support: apiClient.get('/path'), apiClient.post(`/path/${id}`, data)
        for m in axios_re.finditer(src):
          method = str(m.group(1) or "GET").upper()
          raw_endpoint = _strip_quotes(m.group(2))
          path = _extract_api_path(raw_endpoint)
          calls.add(f"{method} {path}")

        return {"ok": True, "routes": calls}

    def _canonical_route_key(self, route_key: str) -> str:
        """Canonicalize METHOD/path for comparisons, tolerating optional /api prefix."""
        s = str(route_key or "").strip()
        if " " not in s:
            return s
        method, path = s.split(" ", 1)
        path_norm = self._normalize_contract_path(path)
        if path_norm.startswith("/api/"):
            path_norm = self._normalize_contract_path(path_norm[len("/api"):])
        elif path_norm == "/api":
            path_norm = "/"
        return f"{method.upper()} {path_norm}"

    def _canonical_route_key_loose_params(self, route_key: str) -> str:
        """Canonicalize METHOD/path while normalizing path-param names to :param."""
        s = self._canonical_route_key(route_key)
        if " " not in s:
            return s
        method, path = s.split(" ", 1)
        path = re.sub(r":[^/]+", ":param", path)
        return f"{method.upper()} {path}"

    def _verify_contract_alignment(self, role_key: str, workspace: str) -> Dict:
        """Role-specific contract checks for backend/frontend against contracts/api_contract.json."""
        if role_key not in {"backend_engineer", "frontend_engineer"}:
            return {"ok": True, "missing": []}

        contract = self._load_contract_routes()
        if not contract.get("ok"):
            return {"ok": False, "missing": [f"contract verification failed: {contract.get('error', 'unknown error')}"]}

        contract_routes = {self._canonical_route_key(r) for r in set(contract.get("routes", {}).keys())}
        missing = []

        if role_key == "backend_engineer":
            actual = self._collect_backend_routes(workspace)
            if not actual.get("ok"):
                return {"ok": False, "missing": [f"backend route verification failed: {actual.get('error', 'unknown error')}"]}

            actual_routes = {self._canonical_route_key(r) for r in set(actual.get("routes", set()))}
            methodless_paths = {
                self._normalize_api_path(p) for p in set(actual.get("methodless_paths", set())) if isinstance(p, str)
            }
            if methodless_paths:
                by_path = {}
                for r in contract_routes:
                    if " " not in r:
                        continue
                    method, path = r.split(" ", 1)
                    by_path.setdefault(path, set()).add(method)
                for path in methodless_paths:
                    methods = by_path.get(path, set())
                    if len(methods) == 1:
                        only_method = next(iter(methods))
                        actual_routes.add(f"{only_method} {path}")

            missing_routes = sorted(contract_routes - actual_routes)
            health_routes = {"GET /health", "GET /healthz", "GET /ping"}
            extra_routes = sorted(r for r in (actual_routes - contract_routes) if r not in health_routes)

            if missing_routes:
                missing.append("backend missing contract routes: " + ", ".join(missing_routes[:20]))
            if extra_routes:
                missing.append("backend defines non-contract routes: " + ", ".join(extra_routes[:20]))

        elif role_key == "frontend_engineer":
            actual = self._collect_frontend_api_calls(workspace)
            if not actual.get("ok"):
                return {"ok": False, "missing": [f"frontend route verification failed: {actual.get('error', 'unknown error')}"]}

            actual_routes = {self._canonical_route_key(r) for r in set(actual.get("routes", set()))}
            contract_loose = {self._canonical_route_key_loose_params(r) for r in contract_routes}
            actual_loose = {self._canonical_route_key_loose_params(r) for r in actual_routes}

            missing_routes = sorted(contract_loose - actual_loose)
            non_contract_calls = sorted(r for r in actual_loose if r not in contract_loose)
            if missing_routes:
                missing.append("frontend missing contract API routes: " + ", ".join(missing_routes[:20]))
            if non_contract_calls:
                missing.append("frontend uses non-contract API routes: " + ", ".join(non_contract_calls[:20]))

        return {"ok": len(missing) == 0, "missing": missing}

    def _validate_contract_globally(self) -> None:
        """Deterministic contract validator after implementation layers finish."""
        failures = []

        backend_ws = self.completed_workspaces.get("backend_engineer")
        if backend_ws:
            out = self._verify_contract_alignment("backend_engineer", backend_ws)
            if not out.get("ok"):
                failures.extend(out.get("missing", []))

        frontend_ws = self.completed_workspaces.get("frontend_engineer")
        if frontend_ws:
            out = self._verify_contract_alignment("frontend_engineer", frontend_ws)
            if not out.get("ok"):
                failures.extend(out.get("missing", []))

        if failures:
            raise RuntimeError("CRITICAL: Contract validation failed: " + "; ".join(failures))

    def _run_local_ast_precheck(self, workspace: str) -> Dict:
        """Lightweight local precheck: parse Python AST and JSON files. Fail on errors only."""
        diagnostics = []
        files = self._list_generated_files(workspace)
        workspace_base = os.path.basename(os.path.normpath(workspace)).replace("\\", "/")

        for rel in files:
            abs_path = os.path.join(workspace, rel)
            rel_norm = rel.replace("\\", "/")

            # Ignore accidental nested duplicate root trees (e.g., backend/backend/*)
            if workspace_base and rel_norm.startswith(workspace_base + "/"):
                continue

            # Ignore dependency/build caches generated by package managers.
            if (
                rel_norm.startswith("node_modules/")
                or "/node_modules/" in rel_norm
                or rel_norm.startswith(".venv/")
                or rel_norm.startswith("venv/")
                or rel_norm.startswith("dist/")
                or rel_norm.startswith("build/")
                or rel_norm.startswith(".git/")
            ):
                continue

            if rel_norm.endswith(".py"):
                try:
                    with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                        source = f.read()
                    ast.parse(source, filename=rel_norm)
                except SyntaxError as e:
                    diagnostics.append({
                        "tool": "local_ast",
                        "severity": "error",
                        "file": rel_norm,
                        "line": int(e.lineno or 1),
                        "column": int((e.offset or 1) - 1),
                        "message": str(e.msg or "Invalid Python syntax")
                    })
                except Exception as e:
                    diagnostics.append({
                        "tool": "local_ast",
                        "severity": "error",
                        "file": rel_norm,
                        "line": 1,
                        "column": 0,
                        "message": f"Failed to parse Python file: {str(e)}"
                    })

            if rel_norm.endswith(".json"):
                try:
                    with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                        json.load(f)
                except json.JSONDecodeError as e:
                    diagnostics.append({
                        "tool": "local_ast",
                        "severity": "error",
                        "file": rel_norm,
                        "line": int(e.lineno or 1),
                        "column": int(e.colno or 1),
                        "message": f"Invalid JSON: {e.msg}"
                    })
                except Exception as e:
                    diagnostics.append({
                        "tool": "local_ast",
                        "severity": "error",
                        "file": rel_norm,
                        "line": 1,
                        "column": 1,
                        "message": f"Failed to parse JSON file: {str(e)}"
                    })

        return {
            "ok": len(diagnostics) == 0,
            "diagnostics": diagnostics,
            "skipped": False,
            "source": "local_ast"
        }

    def _run_local_import_precheck(self, workspace: str) -> Dict:
        """Validate that local relative imports resolve to real files. Fail on unresolved imports only."""
        diagnostics = []
        files = self._list_generated_files(workspace)
        workspace_base = os.path.basename(os.path.normpath(workspace)).replace("\\", "/")

        js_like = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
        rel_import_re = re.compile(r"(?:import\s+[^\n]*?from\s*|import\s*|require\s*\()\s*['\"](\.{1,2}/[^'\"]+)['\"]")

        def _resolve_candidates(base_file_abs: str, spec: str) -> List[str]:
            base_dir = os.path.dirname(base_file_abs)
            raw = os.path.normpath(os.path.join(base_dir, spec))

            # Keep checks within workspace boundaries.
            workspace_abs = os.path.abspath(workspace)
            raw_abs = os.path.abspath(raw)
            if not raw_abs.startswith(workspace_abs):
                return []

            # If extension provided, test exact path only.
            _, ext = os.path.splitext(raw_abs)
            if ext:
                return [raw_abs]

            exts = [".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".json"]
            candidates = [raw_abs + e for e in exts]
            candidates.extend([os.path.join(raw_abs, "index" + e) for e in exts])
            return candidates

        for rel in files:
            rel_norm = rel.replace("\\", "/")

            # Ignore accidental nested duplicate root trees (e.g., backend/backend/*)
            if workspace_base and rel_norm.startswith(workspace_base + "/"):
                continue

            abs_path = os.path.join(workspace, rel)
            ext = os.path.splitext(rel_norm)[1].lower()
            if ext not in js_like:
                continue

            if (
                rel_norm.startswith("node_modules/")
                or "/node_modules/" in rel_norm
                or rel_norm.startswith("dist/")
                or rel_norm.startswith("build/")
                or rel_norm.startswith(".git/")
                or rel_norm.startswith("coverage/")
            ):
                continue

            try:
                with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                    source = f.read()
            except Exception as e:
                diagnostics.append({
                    "tool": "local_import",
                    "severity": "error",
                    "file": rel_norm,
                    "line": 1,
                    "column": 1,
                    "message": f"Failed reading file for import analysis: {str(e)}"
                })
                continue

            for m in rel_import_re.finditer(source):
                spec = (m.group(1) or "").strip()
                if not spec or not spec.startswith(("./", "../")):
                    continue

                candidates = _resolve_candidates(abs_path, spec)
                if not candidates:
                    continue

                if any(os.path.exists(c) for c in candidates):
                    continue

                line = source.count("\n", 0, m.start()) + 1
                diagnostics.append({
                    "tool": "local_import",
                    "severity": "error",
                    "file": rel_norm,
                    "line": line,
                    "column": 1,
                    "message": f"Unresolved local import: {spec}"
                })

        return {
            "ok": len(diagnostics) == 0,
            "diagnostics": diagnostics,
            "skipped": False,
            "source": "local_import"
        }

    def _run_remote_lsp_precheck(self, role: str, workspace: str) -> Dict:
      """Remote LSP precheck (fail on error diagnostics only). Skips if endpoint is not configured."""
      endpoint = os.getenv("LSP_VALIDATOR_URL", "").strip()
      self._log_lsp_precheck(role, workspace, "start", {"endpoint": endpoint or "(not configured)"})
      if not endpoint:
        self._log_lsp_precheck(role, workspace, "skipped", {"reason": "LSP_VALIDATOR_URL not configured"})
        return {
          "ok": True,
          "diagnostics": [],
          "skipped": True,
          "source": "remote_lsp",
          "reason": "LSP_VALIDATOR_URL not configured"
        }

      # Local integration convenience: auto-start local validator if endpoint is localhost.
      try:
        parsed = urlparse(endpoint)
        host = (parsed.hostname or "").lower()
        if host in {"127.0.0.1", "localhost"} and not self._lsp_server_started:
          validator_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "lsp_validator_server.py"))
          if os.path.exists(validator_script):
            subprocess.Popen(
              ["python3", validator_script],
              stdout=subprocess.DEVNULL,
              stderr=subprocess.DEVNULL,
              cwd=os.path.dirname(os.path.abspath(__file__))
            )
            self._lsp_server_started = True
            time.sleep(0.5)
      except Exception:
        # Non-fatal. Infrastructure check failures are handled as skipped below.
        pass

      lsp_files = [
        f for f in self._list_generated_files(workspace)
        if not (
          f.replace("\\", "/").startswith("node_modules/")
          or "/node_modules/" in f.replace("\\", "/")
          or f.replace("\\", "/").startswith("dist/")
          or f.replace("\\", "/").startswith("build/")
          or f.replace("\\", "/").startswith(".git/")
        )
      ]

      payload = {
        "role": role,
        "workspace": os.path.abspath(workspace),
        "files": lsp_files
      }

      try:
        req = urllib.request.Request(
          endpoint,
          data=json.dumps(payload).encode("utf-8"),
          headers={"Content-Type": "application/json"},
          method="POST"
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
          body = resp.read().decode("utf-8", errors="ignore")
        data = json.loads(body) if body else {}

        diagnostics = data.get("diagnostics", [])
        rpc_error = data.get("error")
        if rpc_error:
          diagnostics.append(rpc_error)

        def _is_error(diag: Dict) -> bool:
          sev = str(diag.get("severity", "")).lower()
          # LSP numeric severity: 1=Error, 2=Warning, 3=Info, 4=Hint
          if isinstance(diag.get("severity"), int):
            return int(diag.get("severity")) == 1
          return sev in {"error", "err", "fatal", "critical"}

        has_error = any(_is_error(d) for d in diagnostics if isinstance(d, dict))
        self._log_lsp_precheck(
          role,
          workspace,
          "completed",
          {
            "ok": not has_error,
            "diagnostics_count": len(diagnostics),
            "error_count": len([d for d in diagnostics if isinstance(d, dict) and _is_error(d)])
          }
        )
        return {
          "ok": not has_error,
          "diagnostics": diagnostics,
          "skipped": False,
          "source": "remote_lsp"
        }
      except Exception as e:
        # Infrastructure failure should NOT be fed back as code errors.
        # Skip remote LSP check so agents do not loop trying to "fix" network/server problems.
        self._log_lsp_precheck(role, workspace, "skipped", {"reason": f"Remote LSP unavailable: {str(e)}"})
        return {
          "ok": True,
          "diagnostics": [],
          "skipped": True,
          "source": "remote_lsp",
          "reason": f"Remote LSP unavailable: {str(e)}"
        }

    def _log_lsp_precheck(self, role: str, workspace: str, stage: str, details: Dict):
      try:
        entry = {
          "ts": datetime.now().isoformat(),
          "role": role,
          "workspace": os.path.abspath(workspace),
          "stage": stage,
          "details": details or {}
        }
        with open(LSP_PRECHECK_LOG_PATH, "a", encoding="utf-8") as f:
          f.write(json.dumps(entry, ensure_ascii=False) + "\n")
      except Exception:
        pass

    def _format_lsp_remediation(self, diagnostics: List[Dict], phase: str) -> str:
        """Sanitize diagnostics into actionable feedback for the coding agent."""
        if not diagnostics:
            return "No diagnostics available."

        lines = []
        for d in diagnostics[:10]:
            file_path = d.get("file") or d.get("uri") or "unknown_file"
            line = d.get("line")
            col = d.get("column")
            message = d.get("message") or "Unknown validation error"

            # JSON-RPC-ish shape support: {code, message, range:{start:{line,character}}}
            rng = d.get("range") if isinstance(d.get("range"), dict) else {}
            start = rng.get("start", {}) if isinstance(rng, dict) else {}
            if line is None and isinstance(start, dict):
                line = start.get("line")
            if col is None and isinstance(start, dict):
                col = start.get("character")

            if isinstance(line, int):
                line = line + 1 if "range" in d else line
            else:
                line = 1

            if isinstance(col, int):
                col = col + 1 if "range" in d else col
            else:
                col = 1

            lines.append(
                f"- LSP Syntax Error in '{file_path}' at Line {line}, Column {col}: {message}. "
                "Please fix this specific line/location before resubmitting."
            )

        return "\n".join(lines)

    def _attempt_auto_patch_unresolved_imports(self, workspace: str, diagnostics: List[Dict]) -> Dict:
      """Create safe shim files for unresolved local imports (last-resort recovery)."""
      unresolved_specs: List[Dict] = []
      for d in diagnostics or []:
        if not isinstance(d, dict):
          continue
        msg = str(d.get("message", ""))
        marker = "Unresolved local import:"
        if marker in msg:
          spec = msg.split(marker, 1)[1].strip()
          if spec.startswith(("./", "../")):
            unresolved_specs.append({
              "spec": spec,
              "file": str(d.get("file", "") or "")
            })

      patched = []
      failed = []

      def _no_ext(path_value: str) -> str:
        root, ext = os.path.splitext(path_value)
        return root if ext else path_value

      seen_pairs = set()
      for item in unresolved_specs:
        spec = str(item.get("spec", "") or "")
        from_file = str(item.get("file", "") or "")
        key = (spec, from_file)
        if key in seen_pairs:
          continue
        seen_pairs.add(key)

        try:
          from_abs = os.path.abspath(os.path.join(workspace, from_file)) if from_file else os.path.abspath(workspace)
          from_dir = os.path.dirname(from_abs)
          target_abs = os.path.abspath(os.path.normpath(os.path.join(from_dir, spec)))
          if not target_abs.startswith(os.path.abspath(workspace)):
            failed.append(f"{from_file}: {spec} (outside workspace)")
            continue

          rel_target = os.path.relpath(target_abs, os.path.abspath(workspace)).replace("\\", "/")
          parts = [p for p in rel_target.split("/") if p]
          collapsed = []
          for p in parts:
            if not collapsed or collapsed[-1] != p:
              collapsed.append(p)
          rel_target = "/".join(collapsed)
          target_abs = os.path.abspath(os.path.join(workspace, rel_target))

          if (
            os.path.exists(target_abs)
            or os.path.exists(target_abs + ".js")
            or os.path.exists(os.path.join(target_abs, "index.js"))
          ):
            continue

          target_dir = os.path.dirname(target_abs)
          base = os.path.basename(target_abs)
          os.makedirs(target_dir, exist_ok=True)

          if base == "errorHandler" and os.path.basename(target_dir) == "middleware":
            out_file = target_abs + ".js"
            with open(out_file, "w", encoding="utf-8") as f:
              f.write(
                "function errorHandler(err, req, res, next) {\n"
                "  if (res.headersSent) return next(err);\n"
                "  const status = err && err.statusCode ? err.statusCode : 500;\n"
                "  res.status(status).json({ error: err && err.message ? err.message : 'Internal server error' });\n"
                "}\n\n"
                "module.exports = { errorHandler };\n"
              )
            patched.append(f"{from_file}: {spec} -> middleware/errorHandler.js (generated)")
            continue

          candidate_stems = [
            base,
            base.rstrip("s"),
            base + "s",
            base + "Routes",
            base.rstrip("s") + "Routes",
          ]
          chosen = None
          for stem in candidate_stems:
            candidate_abs = os.path.join(target_dir, stem + ".js")
            if os.path.exists(candidate_abs):
              chosen = candidate_abs
              break

          if chosen is None:
            failed.append(f"{from_file}: {spec} (no suitable target for safe shim)")
            continue

          require_path = os.path.relpath(_no_ext(chosen), target_dir).replace("\\", "/")
          if not require_path.startswith("."):
            require_path = "./" + require_path

          out_file = target_abs + ".js"
          with open(out_file, "w", encoding="utf-8") as f:
            f.write(f"module.exports = require('{require_path}');\n")
          patched.append(f"{from_file}: {spec} -> shim to {require_path}")
        except Exception as e:
          failed.append(f"{from_file}: {spec} ({str(e)})")

      return {"patched": patched, "failed": failed}

    def _collect_workspace_file_set(self, workspace: str) -> set:
      out = set()
      for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in {"node_modules", ".git", "dist", "build", "coverage", "ml", "__pycache__"}]
        for name in files:
          rel = os.path.relpath(os.path.join(root, name), os.path.abspath(WORKSPACE_DIR)).replace("\\", "/")
          out.add(rel)
      return out

    def _extract_paths_from_text(self, text: str) -> set:
      if not text:
        return set()
      path_re = re.compile(
        r"(?:^|\s)([A-Za-z0-9_./-]+\.(?:js|jsx|ts|tsx|json|md|sql|py|toml|txt|env))(?:$|\s|,|;|\))",
        re.IGNORECASE
      )
      out = set()
      for m in path_re.finditer(text):
        p = (m.group(1) or "").strip().lstrip("./")
        if p:
          out.add(p)
      return out

    def _infer_missing_import_target_paths(self, workspace: str, diagnostics: List[Dict]) -> set:
      """Infer missing local import target file paths (workspace-relative) from import diagnostics."""
      out = set()
      ws_abs = os.path.abspath(workspace)
      root_abs = os.path.abspath(WORKSPACE_DIR)
      marker = "Unresolved local import:"

      for d in diagnostics or []:
        if not isinstance(d, dict):
          continue
        msg = str(d.get("message", "") or "")
        if marker not in msg:
          continue
        spec = msg.split(marker, 1)[1].strip()
        src_file = str(d.get("file", "") or "")
        if not spec.startswith(("./", "../")) or not src_file:
          continue

        try:
          src_abs = os.path.abspath(os.path.join(ws_abs, src_file))
          src_dir = os.path.dirname(src_abs)
          target_base_abs = os.path.abspath(os.path.normpath(os.path.join(src_dir, spec)))
          if not target_base_abs.startswith(ws_abs):
            continue

          candidates = [
            target_base_abs + ".js",
            target_base_abs + ".jsx",
            target_base_abs + ".ts",
            target_base_abs + ".tsx",
            os.path.join(target_base_abs, "index.js"),
            os.path.join(target_base_abs, "index.ts"),
          ]
          for c in candidates:
            rel = os.path.relpath(c, root_abs).replace("\\", "/")
            out.add(rel)
        except Exception:
          continue

      return out

    def _configure_retry_write_policy(self, agent, workspace: str, attempt: int, hints: List[str], last_failure_reason: str, extra_allowed_new_paths: Optional[set] = None) -> None:
      if not hasattr(agent, "tools_registry"):
        return
      tr = agent.tools_registry
      if attempt <= 1:
        tr.retry_fix_mode = False
        tr.retry_existing_files = set()
        tr.retry_allowed_new_paths = set()
        tr.max_writes_per_file = int(os.getenv("MAX_WRITES_PER_FILE", "6"))
        return

      tr.retry_fix_mode = True
      tr.retry_existing_files = self._collect_workspace_file_set(workspace)

      allowed_new = set()
      for msg in hints or []:
        allowed_new.update(self._extract_paths_from_text(str(msg)))
      allowed_new.update(self._extract_paths_from_text(str(last_failure_reason or "")))
      if extra_allowed_new_paths:
        allowed_new.update(set(extra_allowed_new_paths))

      # Always permit core manifests/docs in retries.
      role_roots = self._get_role_output_roots(getattr(tr, "agent_role", "") or "")
      if role_roots:
        base = role_roots[0].strip("/")
        allowed_new.update({
          f"{base}/README.md",
          f"{base}/package.json",
          f"{base}/requirements.txt",
          f"{base}/pyproject.toml",
        })

      tr.retry_allowed_new_paths = allowed_new
      tr.max_writes_per_file = min(int(getattr(tr, "max_writes_per_file", 6) or 6), 2)
    
    def _execute_agent(self, agent_spec: Dict, context: Dict, parallel_agents: List[str] = None, layer_blackboard = None, layer_sleep: Optional[LayerSleepCoordinator] = None, layer_index: int = None, current_layer_roles: Optional[List[str]] = None) -> str:
        """Execute an agent using GeneralAgent framework"""
        role = agent_spec.get("role", "unknown")
        role_key = role.lower().replace(" ", "_")
        print(f"[DEBUG] _execute_agent called for role: {role}")
        workspace = self._get_agent_workspace(role)

        # Hard-gate semantic prerequisites (contract-first + upstream readiness)
        self._enforce_role_prerequisites(role, current_layer_roles=current_layer_roles)
        
        if parallel_agents is None:
            parallel_agents = []
        
        # Initialize agents with blackboard access
        set_blackboard(self.blackboard)
        
        # SPECIAL HANDLING FOR QA AGENT: Limit context to prevent token overflow
        # QA agent gets file discovery instructions but not all files listed upfront
        if "qa" in role.lower() or "test" in role.lower():
            upstream_roles = ["database_architect", "security_engineer", "backend_engineer", "frontend_engineer"]
            upstream_agents = {
                r: os.path.join("./workspace", self._get_role_output_roots(r)[0])
                for r in upstream_roles
            }
            context_for_qa = {
                "project_name": context.get("project_name", ""),
                "requirements": context.get("requirements", []),
                "tech_stack": context.get("tech_stack", {}),
                "previous_outputs": context.get("previous_outputs", {}),
                "required_upstream_roles": context.get("required_upstream_roles", []),
                "upstream_agents": upstream_agents,
                "note": "Use read_file() or list_files() to discover upstream code. Do NOT request all files at once."
            }
            context = context_for_qa
        
        print(f"\n🤖 [{role}] Initializing GeneralAgent...")
        
        # Select appropriate agent class based on role
        # NOTE: Pass WORKSPACE_DIR only - agents create their own role-specific subdirs
        if "backend" in role.lower():
          agent = BackendEngineerAgent(allowed_root=workspace)
        elif "frontend" in role.lower():
          agent = FrontendDeveloperAgent(allowed_root=workspace)
        elif "database" in role.lower():
          agent = DatabaseArchitectAgent(allowed_root=workspace)
        elif "security" in role.lower():
          agent = SecurityEngineerAgent(allowed_root=workspace)
        elif "qa" in role.lower() or "test" in role.lower():
          agent = TestEngineerAgent(allowed_root=workspace)
        else:
            agent = GeneralAgent(
                role=role,
                specific_instructions=agent_spec.get("instructions", ""),
            allowed_root=workspace,
                timeout=120
            )

        # Bind per-agent coordination context directly on the tool registry.
        # This avoids cross-thread global state overwrites when agents run in parallel.
        if hasattr(agent, "tools_registry"):
          output_roots = self._get_role_output_roots(role)
          agent.tools_registry.workspace_root = os.path.abspath(WORKSPACE_DIR)
          agent.tools_registry.layer_blackboard = layer_blackboard
          agent.tools_registry.layer_sleep = layer_sleep
          agent.tools_registry.agent_role = role
          agent.tools_registry.notebooks_dir = NOTEBOOKS_DIR
          agent.tools_registry.parallel_peers = list(parallel_agents)
          agent.tools_registry.service_bus = self.service_bus
          agent.tools_registry.write_scope = "workspace"
          agent.tools_registry.preferred_output_roots = list(output_roots)
          agent.tools_registry.primary_output_root = output_roots[0] if output_roots else ""

        # Keep iteration budget explicit and mode-aware.
        is_fix_mode = "SECOND ITERATION - ISSUE FIX MODE" in str(agent_spec.get("instructions", ""))
        if hasattr(agent, "max_iterations"):
          agent.max_iterations = AGENT_MAX_ITERATIONS_FIX if is_fix_mode else AGENT_MAX_ITERATIONS_MAIN
        
        # Build task description
        try:
            parallel_info = ""
            if parallel_agents:
                parallel_info = f"""
PARALLEL AGENTS IN THIS LAYER:
You are executing in parallel with: {', '.join(parallel_agents)}
      BEFORE STARTING WORK: Discuss your implementation plans with them on the layer blackboard.
      You MUST act like one team:
      - Post a detailed plan (inputs, outputs, interfaces, risks, assumptions)
      - Read peers' plans and identify conflicts/dependencies
      - Post a follow-up agreement/alignment note before finishing
      Service Bus is for one-to-one questions only; blackboard is for group coordination and shared understanding."""

            layer_onboarding_text = ""
            role_boundary_text = ""
            output_roots = self._get_role_output_roots(role)
            output_roots_text = "\n".join(f"- {p}" for p in output_roots)
            try:
              onboarding_entries = self.ledger.get("layer_onboarding", [])
              onboarding = None
              if isinstance(onboarding_entries, list) and layer_index is not None:
                for entry in onboarding_entries:
                  if isinstance(entry, dict) and int(entry.get("layer_index", -1)) == int(layer_index + 1):
                    onboarding = entry
                    break
              if onboarding:
                objective = onboarding.get("objective", "")
                outcomes = onboarding.get("required_outcomes", []) or []
                coordination = onboarding.get("coordination_expectations", []) or []
                handoffs = onboarding.get("handoff_contracts", []) or []

                layer_onboarding_text = "\nLAYER ONBOARDING (from Director):\n"
                if objective:
                  layer_onboarding_text += f"- Objective: {objective}\n"
                if outcomes:
                  layer_onboarding_text += "- Required outcomes:\n" + "\n".join(f"  • {o}" for o in outcomes[:12]) + "\n"
                if coordination:
                  layer_onboarding_text += "- Coordination expectations:\n" + "\n".join(f"  • {c}" for c in coordination[:12]) + "\n"
                if handoffs:
                  layer_onboarding_text += "- Handoff contracts:\n" + "\n".join(f"  • {h}" for h in handoffs[:12]) + "\n"

              # Also inject full layer onboarding document when available.
              if layer_index is not None:
                onboarding_doc = os.path.join(WORKSPACE_DIR, "layer_onboarding", f"layer_{layer_index + 1}.md")
                if os.path.exists(onboarding_doc):
                  try:
                    with open(onboarding_doc, "r", encoding="utf-8", errors="ignore") as f:
                      doc_content = f.read().strip()
                    if doc_content:
                      layer_onboarding_text += (
                        f"\nDETAILED LAYER ONBOARDING DOCUMENT (read and follow):\n"
                        f"Source: {onboarding_doc}\n"
                        f"{doc_content}\n"
                      )
                  except Exception:
                    pass
            except Exception:
              pass

            role_norm = (role or "").strip().lower()
            if role_norm == "api_designer":
              role_boundary_text = """

ROLE BOUNDARY (MANDATORY):
- You are the API Designer.
- Your ONLY responsibility is to define a COMPLETE, PRECISE, and UNAMBIGUOUS API CONTRACT.
- You DO NOT write implementation code.

SINGLE SOURCE OF TRUTH (MANDATORY):
- Create and maintain exactly: contracts/api_contract.json
- This file defines ALL backend/frontend communication.

FOR EVERY ENDPOINT, DEFINE (MANDATORY):
1) Route: method + full path
2) Request: query params, path params, strict request body schema
3) Response: exact success JSON shape, exact error JSON shapes, status codes
4) Data types: strict primitive/object/array types only
5) Field names: exact and globally consistent across all endpoints

MANDATORY RULES:
- NO ambiguity: never use "etc", "and so on", "additional fields"
- COMPLETE coverage: every required feature endpoint must exist
- CONSISTENCY: same field names across all related endpoints
- ERROR handling required: include at least 400/404/500 where applicable
- NO implementation: do not create backend/frontend runtime modules

YOU MUST STATE IN CONTRACT/README:
- Backend Engineer MUST implement endpoints EXACTLY as defined
- Frontend Developer MUST consume contract EXACTLY as defined
- No agent may invent routes, field names, or payload formats

SUCCESS CRITERIA:
- Backend/Frontend can implement/use APIs with ZERO guessing
- No missing endpoint/field/response shape
- If any agent must assume a field/shape, contract is incomplete
"""
            elif role_norm == "backend_engineer":
              role_boundary_text = """

ROLE BOUNDARY (MANDATORY):
- Treat contracts/api_contract.json as authoritative API source of truth.
- Implement endpoints, request/response schemas, field names, and status codes EXACTLY as contract defines.
- You MUST NOT invent new routes or payload fields unless contract is updated first.
- Implement production-ready controllers/services and route wiring in your workspace.
- Avoid conflicting duplicate route/module names; ensure imports resolve to real local files.

MANDATORY SELF-CHECK BEFORE READY TOKEN:
- Build a route matrix of contract route -> implemented route.
- Verify HTTP method and full path EXACT match for every contract endpoint.
- Verify path param names EXACT match (e.g., :order_id must not become :id).
- Verify no extra backend API routes exist outside contract.
"""
            elif role_norm == "frontend_engineer":
              role_boundary_text = """

ROLE BOUNDARY (MANDATORY):
- Treat contracts/api_contract.json as authoritative API source of truth.
- Consume API paths, params, payloads, response fields, and error shapes EXACTLY as contract defines.
- You MUST NOT invent frontend-only API fields/routes.
- If API mismatch is found, request contract correction instead of guessing.

MANDATORY SELF-CHECK BEFORE READY TOKEN:
- Build a call matrix of frontend API call -> contract endpoint.
- Verify each API path + method in frontend exists in contracts/api_contract.json.
- Verify path param names EXACT match contract names.
- Verify frontend does not call non-contract endpoints.
"""
            
            task_description = f"""
Project: {context.get('project_name', 'Project')}

Your task as {role}:
{agent_spec.get('instructions', 'Implement your role responsibilities')}{parallel_info}{layer_onboarding_text}{role_boundary_text}

Requirements:
{chr(10).join(f"- {req}" for req in context.get('requirements', []))}

Technology Stack:
- Backend: {', '.join(context.get('tech_stack', {}).get('backend_frameworks', []))}
- Frontend: {', '.join(context.get('tech_stack', {}).get('frontend_frameworks', []))}
- Databases: {', '.join(context.get('tech_stack', {}).get('databases', []))}

CRITICAL WORKSPACE INFO:
- You can create/write files anywhere under: {WORKSPACE_DIR}
- Preferred production output roots for your role:
{output_roots_text}
- If your allowed root already equals your primary output root, write paths relative to it.
  Example: use "controllers/user.js" (not "backend/controllers/user.js") when rooted at backend/.
- Write files to production paths (e.g., backend/, frontend/, database/, infra/, tests/), not role-named folders.
- Respect layer onboarding contracts for target folders/interfaces.

COMPLETION CONTRACT (MANDATORY):
- Do NOT finish after planning only.
- Create real deliverable files first.
- Create a dependency manifest (package.json or requirements.txt).
- Create README.md in your workspace describing architecture, files, setup, and changes.
- Add useful inline comments/docstrings where appropriate.
- Your completion token triggers automatic code checks (local AST/syntax + remote LSP diagnostics).
- If errors are found, you MUST fix them and resubmit [READY_FOR_VERIFICATION].
- When ready, output exactly: [READY_FOR_VERIFICATION]
- The orchestrator verifies your files externally; completion is not self-declared.

QUALITY BAR (MANDATORY):
- Deliver production-quality code, not placeholder scaffolding.
- Frontend must target high visual quality (clear layout, responsive behavior, accessibility, polished UX).
- Resolve integration contracts before completion; do not leave known mismatches unresolved.

DISCOVERY RULES (MANDATORY):
- Do NOT assume upstream contracts.
- Before coding, inspect relevant upstream files with list_files/search_in_files/read_file.
- Required upstream roles for this task: {', '.join(context.get('required_upstream_roles', [])) or 'None'}
- If blocked by a same-layer dependency, use sleep mode and wait for peer wake-up after fix.

EXECUTION EFFICIENCY (MANDATORY):
- Handle multiple deliverables per model iteration (batch related file writes).
- Do not stop at minimum acceptable output; complete core flows end-to-end.
- If changing scope from your plan, record the reason in notebook and continue.

Previous outputs available:
"""

            contract_ctx = context.get("api_contract") if isinstance(context, dict) else None
            if contract_ctx and isinstance(contract_ctx, dict):
                task_description += f"""

INJECTED API CONTRACT CONTEXT (MANDATORY INPUT):
- Source: {contract_ctx.get('path', 'contracts/api_contract.json')}
- SHA256: {contract_ctx.get('checksum_sha256', '')}
- Endpoint count: {contract_ctx.get('endpoint_count', 0)}
- You MUST implement against this exact contract payload (no guessing/no drift):
{contract_ctx.get('content', '')}
"""

            # Add previous agent outputs to task description
            for prev_role, prev_info in context.get("previous_outputs", {}).items():
                task_description += f"\n- {prev_role} workspace: {prev_info['workspace']}"
                task_description += f"\n  Files: {', '.join(prev_info['files'][:5])}"
                if len(prev_info['files']) > 5:
                    task_description += f" (+{len(prev_info['files']) - 5} more)"

            print(f"📋 Task:\n{task_description[:500]}...\n")
        except Exception as e:
            print(f"[ERROR] Failed to build task description: {e}")
            print(f"Context keys: {list(context.keys())}")
            raise
        
        # Execute agent (has full tool suite now)
        print(f"⏳ Agent executing (this may take 1-2 minutes for code generation)...")
        try:
          max_attempts = AGENT_MAX_ATTEMPTS
          result = ""
          verification = {"ok": False, "missing": ["not executed"]}
          last_failure_reason = "unknown failure"
          last_missing_hints: List[str] = []
          last_allowed_new_paths: set = set()

          for attempt in range(1, max_attempts + 1):
            print(f"[DEBUG] About to call agent.execute() for {role} (attempt {attempt}/{max_attempts})")

            if attempt > 1:
              retry_snapshot = self._build_retry_workspace_snapshot(role, workspace)
              task_description += f"""

    RETRY CONTEXT (attempt {attempt}/{max_attempts}):
    - This is a continuation run, NOT a fresh start.
    - Reuse existing artifacts in your workspace.
    - Edit only missing/broken parts; do not rewrite the project from scratch.
    - Previous failure reason: {last_failure_reason}

    {retry_snapshot}
"""

            self._configure_retry_write_policy(
              agent,
              workspace,
              attempt,
              hints=last_missing_hints,
              last_failure_reason=last_failure_reason,
              extra_allowed_new_paths=last_allowed_new_paths,
            )

            api_call_attempt = 0
            while True:
              self._wait_if_globally_paused()
              try:
                while True:
                  result = agent.execute(
                    task_description=task_description,
                    context=context
                  )
                  if (result or "").strip() != "[SLEEP_REQUESTED]":
                    break

                  if layer_sleep is None:
                    raise RuntimeError("Sleep requested but no layer sleep coordinator is configured")

                  print(f"⏸️ [{role}] entered sleep mode waiting for a wake signal...")
                  wake_payload = layer_sleep.wait_until_woken(role, timeout_seconds=600)
                  if not wake_payload:
                    raise RuntimeError(f"{role} sleep timed out waiting for wake-up")

                  wake = wake_payload.get("wake", {})
                  task_description += f"""

SLEEP RESUME CONTEXT:
- Wake signal received from: {wake.get('woken_by', 'peer')}
- Resolution details: {wake.get('resolution', 'No resolution details provided')}
- Re-read relevant files and continue implementation now.
"""
                break
              except Exception as e:
                if self._is_rate_limit_error(e):
                  api_call_attempt += 1
                  if api_call_attempt <= 5:
                    wait_time = self._schedule_global_pause(api_call_attempt)
                    print(f"⏸️ [{role}] Rate limited (429). System paused for ~{wait_time:.1f}s before retry.")
                    continue
                raise
            print(f"[DEBUG] agent.execute() returned for {role}: {len(result) if result else 0} chars")
            if hasattr(agent, "tools_registry"):
              tr = agent.tools_registry
              discovery_ops = int(getattr(tr, "discovery_operations", 0) or 0)
              read_ops = int(getattr(tr, "read_operations", 0) or 0)
              write_ops = int(getattr(tr, "write_operations", 0) or 0)
              cross_reads = int(getattr(tr, "cross_workspace_reads", 0) or 0)
              prewrite_reads = int(getattr(tr, "upstream_reads_before_first_write", 0) or 0)
              print(
                f"[DEBUG] [{role}] tool-ops: discovery={discovery_ops}, reads={read_ops}, "
                f"writes={write_ops}, cross_reads={cross_reads}, prewrite_upstream_reads={prewrite_reads}"
              )
              if write_ops == 0 and discovery_ops >= 10:
                print(
                  f"⚠️ [{role}] high pre-write discovery activity detected "
                  f"({discovery_ops} ops). Agent should pivot to implementation."
                )

            has_ready_token = "[READY_FOR_VERIFICATION]" in (result or "")
            if not has_ready_token:
              normalized_result = (result or "").strip()
              if normalized_result == "NOT_READY_FOR_VERIFICATION":
                last_failure_reason = "agent readiness loop exhausted before emitting token"
                if attempt == max_attempts:
                  print(f"⚠️ [{role}] forcing external verification on final attempt after readiness-loop exhaustion")
                  has_ready_token = True
              else:
                last_failure_reason = "agent did not output [READY_FOR_VERIFICATION]"

            if not has_ready_token:
              if attempt < max_attempts:
                task_description += """

    You are not complete yet.
    You must output exactly [READY_FOR_VERIFICATION] only after you create required files.
    Continue implementation and then emit the token."""
                continue
              break

            # Preliminary gate 1: local AST/syntax precheck (fail on error only)
            local_check = self._run_local_ast_precheck(workspace)
            if not local_check["ok"]:
              last_failure_reason = "local AST precheck failed"
              remediation = self._format_lsp_remediation(local_check.get("diagnostics", []), "LOCAL_AST_PRECHECK")
              last_missing_hints = [remediation]
              last_allowed_new_paths = set()
              print(f"⚠️ [{role}] local AST precheck failed, retrying remediation")
              if attempt < max_attempts:
                task_description += f"""

    LOCAL AST PRECHECK FAILED. You are NOT complete yet.
    Fix these syntax/parsing errors:
    {remediation}

    After fixing, output [READY_FOR_VERIFICATION]."""
                continue
              verification = {
                "ok": False,
                "missing": [f"local AST precheck failed: {remediation}"]
              }
              break

            # Preliminary gate 2: remote LSP precheck (fail on error only)
            import_check = self._run_local_import_precheck(workspace)
            if not import_check["ok"]:
              last_failure_reason = "local import precheck failed"
              remediation = self._format_lsp_remediation(import_check.get("diagnostics", []), "LOCAL_IMPORT_PRECHECK")
              inferred_targets = self._infer_missing_import_target_paths(workspace, import_check.get("diagnostics", []))
              last_missing_hints = [remediation] + [str(d.get("message", "")) for d in (import_check.get("diagnostics", []) or []) if isinstance(d, dict)]
              last_allowed_new_paths = inferred_targets
              print(f"⚠️ [{role}] local import precheck failed, retrying remediation")
              if attempt < max_attempts:
                task_description += f"""

    LOCAL IMPORT PRECHECK FAILED. You are NOT complete yet.
    Fix these unresolved local imports:
    {remediation}

    Ensure every relative import path points to a real file/module in workspace.
    After fixing, output [READY_FOR_VERIFICATION]."""
                continue

              # Last-resort auto patching for unresolved local imports.
              auto_patch = self._attempt_auto_patch_unresolved_imports(workspace, import_check.get("diagnostics", []))
              if auto_patch.get("patched"):
                print(f"🩹 [{role}] auto-patched unresolved imports: {len(auto_patch.get('patched', []))}")
                import_check = self._run_local_import_precheck(workspace)
                if import_check["ok"]:
                  print(f"✅ [{role}] import precheck passed after auto patch")
                else:
                  remediation = self._format_lsp_remediation(import_check.get("diagnostics", []), "LOCAL_IMPORT_PRECHECK")
                  verification = {
                    "ok": False,
                    "missing": [f"local import precheck failed after auto patch: {remediation}"]
                  }
                  break
              else:
                verification = {
                  "ok": False,
                  "missing": [f"local import precheck failed: {remediation}"]
                }
                break

              if auto_patch.get("failed"):
                print(f"⚠️ [{role}] auto-patch failures: {'; '.join(auto_patch.get('failed', [])[:5])}")

              # Continue pipeline (remote checks + deliverable checks) after successful auto patch.
              


            # Preliminary gate 3: remote LSP precheck (fail on error only)
            remote_check = self._run_remote_lsp_precheck(role, workspace)
            if remote_check.get("skipped"):
              print(f"ℹ️ [{role}] remote LSP precheck skipped: {remote_check.get('reason', 'not configured')}")
            elif not remote_check["ok"]:
              last_failure_reason = "remote LSP precheck failed"
              remediation = self._format_lsp_remediation(remote_check.get("diagnostics", []), "REMOTE_LSP_PRECHECK")
              last_missing_hints = [remediation]
              last_allowed_new_paths = set()
              print(f"⚠️ [{role}] remote LSP precheck failed, retrying remediation")
              if attempt < max_attempts:
                task_description += f"""

    REMOTE LSP PRECHECK FAILED. You are NOT complete yet.
    Fix these reported errors:
    {remediation}

    After fixing, output [READY_FOR_VERIFICATION]."""
                continue
              verification = {
                "ok": False,
                "missing": [f"remote LSP precheck failed: {remediation}"]
              }
              break

            verification = self._verify_agent_deliverables(role, workspace)
            if verification["ok"]:
              runtime_check = self._run_post_verification_runtime_check(role_key, workspace)
              if runtime_check.get("ok"):
                checks = runtime_check.get("checks", []) or []
                if checks:
                  summary = ", ".join(
                    f"npm run {c.get('script')} ({'ok' if c.get('ok') else 'fail'})" for c in checks
                  )
                  print(f"✅ [{role}] runtime smoke checks passed: {summary}")
                break

              runtime_err = runtime_check.get("error", "runtime smoke check failed")
              runtime_out = (runtime_check.get("output", "") or "")[-3000:]
              last_failure_reason = f"runtime smoke check failed: {runtime_err}"
              last_missing_hints = [runtime_err, runtime_out]
              last_allowed_new_paths = set()
              print(f"⚠️ [{role}] runtime smoke failed, retrying remediation")
              if attempt < max_attempts:
                task_description += f"""

    POST-VERIFICATION RUNTIME SMOKE CHECK FAILED.
    Runtime failure: {runtime_err}

    Runtime output tail:
    {runtime_out}

    Fix runtime/startup/build issues and output [READY_FOR_VERIFICATION]."""
                continue

              verification = {
                "ok": False,
                "missing": [f"runtime smoke check failed: {runtime_err}"]
              }
              break

            # Option C remediation pass: feed missing items and retry once.
            if attempt < max_attempts:
              missing_text = "\n".join(f"- {m}" for m in verification["missing"])
              last_failure_reason = f"deliverable verification failed: {missing_text}"
              last_missing_hints = list(verification.get("missing", []) or [])
              last_allowed_new_paths = set()
              print(f"⚠️ [{role}] verification failed, retrying with remediation:\n{missing_text}")
              task_description += f"""

    EXTERNAL VERIFICATION FAILED. You are NOT complete yet.
    Missing requirements:
    {missing_text}

    Create the missing files now, then output [READY_FOR_VERIFICATION]."""

          if not verification["ok"]:
            missing_text = "; ".join(verification["missing"])
            if missing_text:
              last_failure_reason = f"verification failed: {missing_text}"
            raise RuntimeError(f"Validation failed for {role}: {last_failure_reason}")

          # Extract summary from result and post to blackboard
          try:
            # Try to parse JSON from result
            import json
            if "{" in result:
              json_start = result.find("{")
              json_end = result.rfind("}") + 1
              summary_data = json.loads(result[json_start:json_end])
              summary_text = summary_data.get("summary", f"{role} completed execution")
            else:
              summary_text = f"{role} completed execution"
          except:
            summary_text = f"{role} completed execution"

          # Post to blackboard
          self.blackboard.post(role, "Implementation plan", summary_text)

          # Track this workspace for future layers
          self.completed_workspaces[role] = workspace

          print(f"✅ [{role}] Completed successfully (externally verified)")
          print(f"📁 Workspace: {workspace}")
          print(f"📄 Files created: {verification['files_count']}")

          return result
        except Exception as e:
            print(f"❌ [{role}] Error: {e}")
            self.blackboard.post(role, "Issues", f"Error during execution: {str(e)}")
            raise
    
    def execute_layer(
        self,
        layer_index: int,
        agents_in_layer: List[Dict],
        total_layers: int = None,
        layer_blackboard_path: str = None,
        phase_label: str = "LAYER"
    ):
        """Execute all agents in a layer in parallel"""
        if total_layers is None:
            total_layers = len(self.execution_layers)

        print(f"\n{'='*70}")
        print(f"{phase_label} {layer_index + 1}/{total_layers}")
        print(f"{'='*70}")
        agent_roles = [a.get('role') for a in agents_in_layer]
        print(f"Agents: {agent_roles}\n")
        
        # Create per-layer blackboard for coordination
        layer_blackboard = LayerBlackboard(layer_index + 1, path=layer_blackboard_path)
        self.layer_blackboards[layer_index] = layer_blackboard

        # Pre-create Service Bus subscriptions for this layer so early questions are not missed.
        try:
          if self.service_bus is not None and self.service_bus.is_enabled():
            self.service_bus.ensure_subscriptions([r for r in agent_roles if r])
        except Exception as e:
          print(f"⚠️ Service Bus subscription warmup failed for layer {layer_index + 1}: {e}")
        
        # Show what previous agents planned/completed (coordination visibility)
        if layer_index > 0:
            print(f"📋 PREVIOUS LAYER COORDINATION:\n")
            discussions = self.blackboard.read_section("Discussions")
            if discussions and "empty" not in discussions.lower():
                print(f"{discussions}\n")
            plans = self.blackboard.read_section("Implementation plan")
            if plans and "empty" not in plans.lower():
                print(f"{plans}\n")
            
            # Show any blocking issues
            issues_tracker = get_issues_tracker()
            open_issues = issues_tracker.get_open_issues()
            if open_issues:
                print(f"⚠️ BLOCKING ISSUES FROM PREVIOUS LAYERS:\n")
                for issue in open_issues:
                    print(f"  [{issue['severity']}] {issue['component']}")
                    print(f"    Reported by: {issue['reported_by']}")
                    print(f"    Assigned to: {issue['assigned_to']}\n")
        
        # Build per-layer sleep coordinator for same-layer dependency handling.
        layer_sleep = LayerSleepCoordinator(agent_roles)
        
        # Start all agents in parallel
        threads = []
        results = {}
        
        def run_agent(agent_spec):
            try:
                # Check if agent has blocking issues before running
                role = agent_spec.get('role')
                issues_tracker = get_issues_tracker()
                blocking_issues = issues_tracker.get_blocking_issues(role)
                
                if blocking_issues:
                    print(f"\n⚠️ Agent {role} has {len(blocking_issues)} blocking issue(s). Checking for resolutions...\n")
                    # Wait a moment for other agents to potentially resolve
                    time.sleep(2)
                    blocking_issues = issues_tracker.get_blocking_issues(role)
                
                if blocking_issues:
                    print(f"🚫 Agent {role} SKIPPED - Still has blocking issues:")
                    for issue in blocking_issues:
                        print(f"    [{issue['severity']}] {issue['component']} (assigned to {issue['assigned_to']})")
                    results[role] = f"SKIPPED: {len(blocking_issues)} blocking issue(s)"
                    return
                
                # Agent is clear to proceed - pass parallel agents and layer blackboard
                parallel_agents = [a.get('role') for a in agents_in_layer if a.get('role') != role]
                context = self._build_cross_layer_context(role)
                current_layer_roles = [a.get('role') for a in agents_in_layer if a.get('role')]
                result = self._execute_agent(
                  agent_spec,
                  context,
                  parallel_agents,
                  layer_blackboard,
                  layer_sleep=layer_sleep,
                  layer_index=layer_index,
                  current_layer_roles=current_layer_roles
                )
                results[agent_spec.get('role')] = result
            except Exception as e:
                import traceback
                print(f"\n[THREAD ERROR in {agent_spec.get('role')}] {e}")
                print(traceback.format_exc())
                results[agent_spec.get('role')] = f"ERROR: {e}"
        
        for agent_spec in agents_in_layer:
            stagger = random.uniform(LAYER_STAGGER_MIN_SECONDS, LAYER_STAGGER_MAX_SECONDS)
            time.sleep(stagger)
            thread = threading.Thread(target=run_agent, args=(agent_spec,))
            threads.append(thread)
            thread.start()
        
        # Wait for all agents to complete
        max_wait_seconds = LAYER_MAX_WAIT_SECONDS
        deadline = time.time() + max_wait_seconds
        for thread in threads:
          remaining = max(0, deadline - time.time())
          thread.join(timeout=remaining)

        stuck_threads = [t for t in threads if t.is_alive()]
        if stuck_threads:
          stuck_count = len(stuck_threads)
          raise TimeoutError(f"Layer {layer_index + 1} timed out with {stuck_count} stuck agent thread(s) after {max_wait_seconds}s")

        error_results = {
            role: outcome
            for role, outcome in results.items()
            if isinstance(outcome, str) and outcome.startswith("ERROR:")
        }
        if error_results:
          summary = "; ".join(f"{r}: {v}" for r, v in error_results.items())
          raise RuntimeError(f"Layer {layer_index + 1} had agent failures: {summary}")

        skipped_results = {
            role: outcome
            for role, outcome in results.items()
            if isinstance(outcome, str) and outcome.startswith("SKIPPED:")
        }
        if skipped_results:
          summary = "; ".join(f"{r}: {v}" for r, v in skipped_results.items())
          raise RuntimeError(f"Layer {layer_index + 1} had skipped agents: {summary}")
        
        print(f"\n✅ Layer {layer_index + 1} completed!")
        return results
    
    def execute_all_layers(self):
      """Execute all layers sequentially"""
      print(f"\n🚀 STARTING ENHANCED MULTI-AGENT EXECUTION")
      print(f"Project: {self.ledger.get('project_name')}")
      print(f"Total Layers: {len(self.execution_layers)}\n")

      # Global contract-first gate.
      self._require_global_contract()

      # Clear blackboard and issues for fresh start
      self.blackboard.clear()
      issues_tracker = get_issues_tracker()
      issues_tracker.clear()

      # Post project summary
      tech_stack = self.ledger.get('technology_stack', {})
      if isinstance(tech_stack, dict):
        tech_preview = ', '.join(tech_stack.get('backend_frameworks', []) or [])
      elif isinstance(tech_stack, list):
        tech_preview = ', '.join([str(x) for x in tech_stack[:6]])
      else:
        tech_preview = ''
      summary = f"E-Commerce platform with {len(self.ledger.get('agent_specifications', {}).get('required_agents', []))} agents. Tech: {tech_preview}"
      self.blackboard.post("System", "Implementation plan", summary)

      # Execute each layer
      for layer_index, agents_in_layer in enumerate(self.execution_layers):
        try:
          # Contract-first hardening: after api_designer layer, ensure contract has usable routes.
          if layer_index >= 1:
            self._auto_heal_empty_contract()
          self.execute_layer(layer_index, agents_in_layer)
        except Exception as e:
          print(f"❌ Error in layer {layer_index + 1}: {e}")
          wake_count = self._run_issue_wake_cycle(trigger=f"layer_{layer_index + 1}_failure")
          if wake_count <= 0:
            raise

          print(f"🔁 Retrying layer {layer_index + 1} after wake-up fixes...")
          self.execute_layer(layer_index, agents_in_layer)

        # Proactively process cross-layer issues after each successful layer.
        self._run_issue_wake_cycle(trigger=f"layer_{layer_index + 1}_post")

      # Deterministic semantic validation across produced backend/frontend artifacts.
      self._validate_contract_globally()

      # Run review + second iteration (issue-fix cycle)
      self._execute_second_iteration()

      print(f"\n{'='*70}")
      print(f"✅ ALL LAYERS COMPLETED SUCCESSFULLY")
      print(f"{'='*70}")
      print(f"\nBlackboard: {self.blackboard.path}")
      print(f"Agent workspaces: {WORKSPACE_DIR}/[agent_role]/\n")


def main():
    """Main entry point"""
    import sys
    
    if len(sys.argv) > 1:
        ledger_id = sys.argv[1]
    else:
        ledger_files = sorted(
            [f for f in os.listdir(WORKSPACE_DIR) if f.startswith("ledger_") and f.endswith(".json")],
            reverse=True
        )
        
        if not ledger_files:
            print("❌ No task ledgers found in workspace!")
            print("Usage: python agent_orchestrator_v3.py [ledger_id]")
            return
        
        ledger_id = ledger_files[0].replace("ledger_", "").replace(".json", "")
        print(f"📋 Using most recent ledger: {ledger_id}\n")
    
    try:
        orchestrator = EnhancedAgentOrchestrator(ledger_id)
        
        print(f"📊 Execution Plan:")
        for i, layer in enumerate(orchestrator.execution_layers, 1):
            roles = [a.get("role") for a in layer]
            print(f"  Layer {i}: {', '.join(roles)}")
        
        orchestrator.execute_all_layers()
        
    except Exception as e:
        print(f"❌ Orchestration failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()


# ─────────────────────────────────────────────────────────────────────────
# AZURE DEPLOYMENT AGENT
# Merged from deployment_agent_azure.py
# ─────────────────────────────────────────────────────────────────────────

# Imports required by AzureDeploymentAgent
import argparse
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

class CheckResult:
    name: str
    ok: bool
    details: str


@dataclass
class DeploymentResult:
    status: str
    mode: str
    message: str
    details: Dict[str, str]


class AzureDeploymentAgent:
    def __init__(
        self,
        project_root: Path,
        project_name: str,
        backend_rel: str = "workspace/backend_engineer",
        frontend_rel: str = "workspace/frontend_engineer",
    ) -> None:
        self.project_root = project_root
        self.project_name = project_name
        self.backend_dir = project_root / backend_rel
        self.frontend_dir = project_root / frontend_rel

        self.azure_dir = project_root / "deployment" / "azure"
        self.output_file = project_root / "workspace" / "azure_deployment_todo.md"
        self.deploy_result = self.azure_dir / "deployment_result.json"
        self.mock_env = self.azure_dir / "mock.secrets.env"
        self.backend_dockerfile = self.backend_dir / "Dockerfile"
        self.frontend_dockerfile = self.frontend_dir / "Dockerfile"
        self.frontend_nginx_conf = self.frontend_dir / "nginx.conf"
        self.bicep_file = self.azure_dir / "main.bicep"
        self.bicep_params = self.azure_dir / "main.parameters.json"

        self.tools: Dict[str, Callable[..., DeploymentResult]] = {
            "deploy_to_azure": self.deploy_to_azure,
        }

    def run(self) -> Path:
        self.generate_artifacts()
        self.create_mock_secrets()
        checks = self._run_local_checks()
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        self.output_file.write_text(self._render_markdown(checks), encoding="utf-8")
        return self.output_file

    def run_tool(self, tool_name: str, **kwargs) -> DeploymentResult:
        tool = self.tools.get(tool_name)
        if not tool:
            return DeploymentResult(
                status="failed",
                mode="tool",
                message=f"Unknown tool: {tool_name}",
                details={"available_tools": ", ".join(self.tools.keys())},
            )
        return tool(**kwargs)

    def generate_artifacts(self) -> None:
        self.azure_dir.mkdir(parents=True, exist_ok=True)
        self.backend_dir.mkdir(parents=True, exist_ok=True)
        self.frontend_dir.mkdir(parents=True, exist_ok=True)

        self.backend_dockerfile.write_text(
            """FROM node:18-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install --omit=dev
COPY . .
EXPOSE 5000
CMD [\"npm\", \"start\"]
""",
            encoding="utf-8",
        )

        self.frontend_nginx_conf.write_text(
            """server {
  listen 80;
  server_name _;
  root /usr/share/nginx/html;
  index index.html;
  location / { try_files $uri /index.html; }
}
""",
            encoding="utf-8",
        )

        self.frontend_dockerfile.write_text(
            """FROM node:18-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/build /usr/share/nginx/html
EXPOSE 80
CMD [\"nginx\", \"-g\", \"daemon off;\"]
""",
            encoding="utf-8",
        )

        self.bicep_file.write_text(
            """param location string = resourceGroup().location
param projectName string
param logAnalyticsName string = '${projectName}-law'
param containerAppEnvName string = '${projectName}-env'

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource containerAppEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: containerAppEnvName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: listKeys(logAnalytics.id, '2022-10-01').primarySharedKey
      }
    }
  }
}

output containerAppEnvironmentId string = containerAppEnv.id
""",
            encoding="utf-8",
        )

        self.bicep_params.write_text(
            json.dumps(
                {
                    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
                    "contentVersion": "1.0.0.0",
                    "parameters": {
                        "projectName": {"value": self.project_name}
                    },
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def create_mock_secrets(self) -> Path:
        self.azure_dir.mkdir(parents=True, exist_ok=True)
        mock_values = {
            "AZURE_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000000",
            "AZURE_RESOURCE_GROUP": "agentic_brocode",
            "AZURE_LOCATION": "southeastasia",
            "JWT_SECRET": f"mock-jwt-{secrets.token_hex(16)}",
            "DB_USER": "mock_user",
            "DB_PASSWORD": "mock_password",
            "DB_HOST": "mock-db.postgres.database.azure.com",
            "DB_PORT": "5432",
            "DB_NAME": "mockdb",
        }
        self.mock_env.write_text("\n".join([f"{k}={v}" for k, v in mock_values.items()]) + "\n", encoding="utf-8")
        return self.mock_env

    def deploy_to_azure(
        self,
        mock_success: bool = False,
        resource_group: str = "agentic_brocode",
        location: str = "southeastasia",
    ) -> DeploymentResult:
        self.generate_artifacts()
        self.create_mock_secrets()

        az_path = shutil.which("az")
        if mock_success or not az_path:
            result = DeploymentResult(
                status="succeeded",
                mode="mock",
                message="Mock deployment succeeded.",
                details={
                    "reason": "forced-mock" if mock_success else "az-cli-not-found",
                    "mock_env_file": str(self.mock_env),
                },
            )
            self._write_deployment_result(result)
            return result

        if not self._is_azure_logged_in(az_path):
            result = DeploymentResult(
                status="failed",
                mode="real",
                message="Azure CLI is not logged in.",
                details={"hint": "Run az login --use-device-code"},
            )
            self._write_deployment_result(result)
            return result

        try:
            suffix = str(random.randint(10000, 99999))
            safe = "".join(ch for ch in self.project_name.lower() if ch.isalnum())[:14] or "agentic"
            acr_name = f"{safe}{suffix}acr"[:50]
            env_name = f"{safe}-env"[:32]
            backend_name = f"{safe}-{suffix}-backend"[:32]
            frontend_name = f"{safe}-{suffix}-frontend"[:32]

            self._run_az(az_path, ["group", "create", "-n", resource_group, "-l", location])
            self._run_az(az_path, ["extension", "add", "-n", "containerapp", "-y"])
            self._run_az(az_path, ["acr", "create", "-g", resource_group, "-n", acr_name, "--sku", "Basic", "--admin-enabled", "true"])

            existing_env = self._find_existing_containerapp_env(az_path, resource_group, location)
            if existing_env:
                env_name = existing_env
            else:
                self._run_az(
                    az_path,
                    ["containerapp", "env", "create", "-g", resource_group, "-n", env_name, "--location", location],
                )

            acr_server = self._run_az(az_path, ["acr", "show", "-n", acr_name, "--query", "loginServer", "-o", "tsv"]).strip()
            acr_user = self._run_az(az_path, ["acr", "credential", "show", "-n", acr_name, "--query", "username", "-o", "tsv"]).strip()
            acr_pass = self._run_az(az_path, ["acr", "credential", "show", "-n", acr_name, "--query", "passwords[0].value", "-o", "tsv"]).strip()

            backend_image = f"{acr_server}/backend:latest"
            frontend_image = f"{acr_server}/frontend:latest"

            self._docker_login(acr_server, acr_user, acr_pass)
            self._docker_build_and_push(self.backend_dir, backend_image)
            self._docker_build_and_push(self.frontend_dir, frontend_image)

            jwt = os.getenv("JWT_SECRET", f"mock-jwt-{secrets.token_hex(16)}")
            db_user = os.getenv("DB_USER", "mock_user")
            db_password = os.getenv("DB_PASSWORD", "mock_password")
            db_host = os.getenv("DB_HOST", "mock-db.postgres.database.azure.com")
            db_port = os.getenv("DB_PORT", "5432")
            db_name = os.getenv("DB_NAME", "mockdb")

            self._run_az(
                az_path,
                [
                    "containerapp", "create",
                    "-g", resource_group,
                    "-n", backend_name,
                    "--environment", env_name,
                    "--image", backend_image,
                    "--target-port", "5000",
                    "--ingress", "external",
                    "--registry-server", acr_server,
                    "--registry-username", acr_user,
                    "--registry-password", acr_pass,
                    "--env-vars",
                    f"NODE_ENV=production JWT_SECRET={jwt} DB_USER={db_user} DB_PASSWORD={db_password} DB_HOST={db_host} DB_PORT={db_port} DB_NAME={db_name}",
                ],
            )

            self._run_az(
                az_path,
                [
                    "containerapp", "create",
                    "-g", resource_group,
                    "-n", frontend_name,
                    "--environment", env_name,
                    "--image", frontend_image,
                    "--target-port", "80",
                    "--ingress", "external",
                    "--registry-server", acr_server,
                    "--registry-username", acr_user,
                    "--registry-password", acr_pass,
                ],
            )

            backend_fqdn = self._run_az(az_path, ["containerapp", "show", "-g", resource_group, "-n", backend_name, "--query", "properties.configuration.ingress.fqdn", "-o", "tsv"]).strip()
            frontend_fqdn = self._run_az(az_path, ["containerapp", "show", "-g", resource_group, "-n", frontend_name, "--query", "properties.configuration.ingress.fqdn", "-o", "tsv"]).strip()

            result = DeploymentResult(
                status="succeeded",
                mode="real",
                message="Azure Container Apps deployment succeeded.",
                details={
                    "resource_group": resource_group,
                    "location": location,
                    "environment": env_name,
                    "acr": acr_name,
                    "backend_app": backend_name,
                    "frontend_app": frontend_name,
                    "backend_url": f"https://{backend_fqdn}" if backend_fqdn else "",
                    "frontend_url": f"https://{frontend_fqdn}" if frontend_fqdn else "",
                },
            )
            self._write_deployment_result(result)
            return result
        except subprocess.CalledProcessError as exc:
            result = DeploymentResult(
                status="failed",
                mode="real",
                message="Azure deployment failed.",
                details={
                    "stderr": (exc.stderr or "")[-4000:],
                    "stdout": (exc.stdout or "")[-4000:],
                },
            )
            self._write_deployment_result(result)
            return result

    def _is_azure_logged_in(self, az_path: str) -> bool:
        try:
            subprocess.run([az_path, "account", "show", "-o", "none"], check=True, capture_output=True, text=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def _run_az(self, az_path: str, args: List[str]) -> str:
        completed = subprocess.run([az_path, *args], check=True, capture_output=True, text=True)
        return completed.stdout

    def _find_existing_containerapp_env(self, az_path: str, resource_group: str, location: str) -> Optional[str]:
        try:
            raw = self._run_az(az_path, ["containerapp", "env", "list", "-g", resource_group, "-o", "json"])
            items = json.loads(raw)
            if not isinstance(items, list) or not items:
                return None

            target_loc = (location or "").strip().lower().replace(" ", "")
            for env in items:
                env_loc = str(env.get("location", "")).strip().lower().replace(" ", "")
                if env_loc == target_loc:
                    return env.get("name")

            # Fallback: if any env exists in RG, use first one.
            first_name = items[0].get("name")
            return first_name if first_name else None
        except Exception:
            return None

    def _docker_login(self, registry: str, username: str, password: str) -> None:
        subprocess.run(
            ["docker", "login", registry, "-u", username, "-p", password],
            check=True,
            capture_output=True,
            text=True,
        )

    def _docker_build_and_push(self, context_dir: Path, image_name: str) -> None:
        subprocess.run(
            ["docker", "build", "-t", image_name, str(context_dir)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["docker", "push", image_name],
            check=True,
            capture_output=True,
            text=True,
        )

    def _write_deployment_result(self, result: DeploymentResult) -> None:
        self.azure_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": result.status,
            "mode": result.mode,
            "message": result.message,
            "details": result.details,
        }
        self.deploy_result.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def _run_local_checks(self) -> List[CheckResult]:
        backend_pkg = self.backend_dir / "package.json"
        frontend_pkg = self.frontend_dir / "package.json"
        backend_app = self.backend_dir / "app.js"

        return [
            CheckResult("Backend workspace exists", self.backend_dir.exists(), str(self.backend_dir)),
            CheckResult("Frontend workspace exists", self.frontend_dir.exists(), str(self.frontend_dir)),
            CheckResult("Backend package.json", backend_pkg.exists(), str(backend_pkg)),
            CheckResult("Frontend package.json", frontend_pkg.exists(), str(frontend_pkg)),
            CheckResult("Backend app.js", backend_app.exists(), str(backend_app)),
        ]

    def _render_markdown(self, checks: List[CheckResult]) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        lines = [
            "# Azure Deployment TODO (Container Apps)",
            "",
            f"Generated: {ts}",
            f"Project: {self.project_name}",
            "",
            "## Local checks",
            "",
        ]
        for c in checks:
            lines.append(f"- {'✅' if c.ok else '❌'} {c.name} — {c.details}")
        lines.extend([
            "",
            "## Target",
            "- Resource Group: agentic_brocode",
            "- Location: southeastasia",
            "- Runtime: Azure Container Apps (backend + frontend)",
            "",
        ])
        return "\n".join(lines) + "\n"

