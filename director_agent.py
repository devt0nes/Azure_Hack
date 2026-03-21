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