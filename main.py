import asyncio
import json
import uuid
import os
import logging
import re
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Set, Tuple
from enum import Enum
from pathlib import Path
from dotenv import load_dotenv

# --- Azure & AI Imports ---
from azure.cosmos import CosmosClient, PartitionKey
from azure.servicebus.aio import ServiceBusClient
from azure.servicebus import ServiceBusMessage
from openai import AzureOpenAI

# Load environment variables from .env file
load_dotenv()

# ==========================================
# 0. SUPPRESS VERBOSE AZURE LOGGING
# ==========================================
logging.getLogger("azure.cosmos").setLevel(logging.WARNING)
logging.getLogger("azure.servicebus").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("azure.core").setLevel(logging.WARNING)

# ==========================================
# 1. CONFIGURATION (From .env)
# ==========================================
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")

COSMOS_CONNECTION_STR = os.getenv("COSMOS_CONNECTION_STR")
DATABASE_NAME = os.getenv("DATABASE_NAME", "agentic-nexus-db")
LEDGER_CONTAINER = os.getenv("LEDGER_CONTAINER", "TaskLedgers")
AGENT_CONTAINER = os.getenv("AGENT_CONTAINER", "AgentRegistry")

SERVICE_BUS_STR = os.getenv("SERVICE_BUS_STR")
GHOST_HANDSHAKE_QUEUE = os.getenv("GHOST_HANDSHAKE_QUEUE", "agent-handshake-stubs")
AGENT_COORDINATION_TOPIC = os.getenv("AGENT_COORDINATION_TOPIC", "agent-coordination-events")
AGENT_EXECUTION_QUEUE = os.getenv("AGENT_EXECUTION_QUEUE", "agent-execution-queue")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
MAX_PARALLEL_AGENTS = int(os.getenv("MAX_PARALLEL_AGENTS", "5"))
AGENT_TIMEOUT_SECONDS = int(os.getenv("AGENT_TIMEOUT_SECONDS", "300"))
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Configure logging
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(message)s'  # Simplified format - only show message
)
logger = logging.getLogger(__name__)

# Create output directory for generated code
OUTPUT_DIR = Path("./generated_code")
OUTPUT_DIR.mkdir(exist_ok=True)
(OUTPUT_DIR / "agents").mkdir(exist_ok=True)
(OUTPUT_DIR / "shared").mkdir(exist_ok=True)

# ==========================================
# 2. AGENT ROLE ENUMS & DEFINITIONS
# ==========================================
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

class AgentSpecialty(str, Enum):
    """Agent specializations within their role."""
    AZURE_INFRASTRUCTURE = "azure_infrastructure"
    MICROSERVICES = "microservices"
    API_DEVELOPMENT = "api_development"
    REACT_FRONTEND = "react_frontend"
    ANGULAR_FRONTEND = "angular_frontend"
    DATABASE_DESIGN = "database_design"
    SECURITY_COMPLIANCE = "security_compliance"
    TESTING_AUTOMATION = "testing_automation"
    ML_INTEGRATION = "ml_integration"
    DEVOPS_CI_CD = "devops_ci_cd"

# ==========================================
# 3. AGENT COMMUNICATION HUB [NEW]
# ==========================================
class AgentCommunicationHub:
    """
    Shared workspace for agent communication and code sharing.
    Agents can read/write to this hub to coordinate work.
    """
    def __init__(self, cosmos_manager):
        self.cosmos_manager = cosmos_manager
        self.messages: Dict[str, List[Dict]] = {}  # agent_id -> [messages]
        self.shared_artifacts: Dict[str, str] = {}  # artifact_name -> content
    
    async def send_message(self, from_agent: str, to_agent: str, message: Dict):
        """Send a message from one agent to another."""
        if to_agent not in self.messages:
            self.messages[to_agent] = []
        self.messages[to_agent].append({
            "from": from_agent,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "content": message
        })
    
    async def get_messages(self, agent_id: str) -> List[Dict]:
        """Retrieve messages for an agent."""
        messages = self.messages.get(agent_id, [])
        self.messages[agent_id] = []  # Clear after retrieval
        return messages
    
    async def publish_artifact(self, artifact_name: str, content: str):
        """Publish a code artifact that other agents can access."""
        self.shared_artifacts[artifact_name] = content
    
    async def get_artifact(self, artifact_name: str) -> Optional[str]:
        """Retrieve a published artifact."""
        return self.shared_artifacts.get(artifact_name)
    
    async def get_all_artifacts(self) -> Dict[str, str]:
        """Get all published artifacts."""
        return self.shared_artifacts.copy()

# ==========================================
# 4. TASK LEDGER MODEL (ENHANCED) [cite: 356, 46, 47]
# ==========================================
class TaskLedger:
    """
    Comprehensive task ledger containing all project metadata,
    agent specifications, and execution graph.
    """
    def __init__(self, user_intent: str, owner_id: str):
        project_id = str(uuid.uuid4())[:8]
        self.data = {
            "id": project_id,
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
            "timeline_budget": "Hackathon 2026",
            "architecture_pattern": "",
            "design_principles": [],
            "guardrail_overrides": [],
            "operation_log": [],
            "revision_history": [],
            "status": "DRAFT",
            # Agent DAG Specification
            "agent_specifications": {
                "required_agents": [],  # List of {role, specialty, count}
                "agent_dependencies": {},  # DAG: agent_id -> [dependent_agent_ids]
                "agent_handoff_rules": {},  # Coordination rules between agents
                "parallel_execution_groups": []  # Groups of agents that can run in parallel
            },
            "technology_stack": {
                "backend_frameworks": [],
                "frontend_frameworks": [],
                "databases": [],
                "messaging_systems": [],
                "cloud_services": [],
                "development_tools": []
            },
            "api_specifications": [],
            "database_schemas": [],
            "security_requirements": [],
            "testing_strategy": []
        }

    def add_revision(self, summary: str):
        self.data["revision_history"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "change_summary": summary
        })

    def update_agents(self, agents: List[Dict]):
        """Update the agent specifications in the ledger."""
        self.data["agent_specifications"]["required_agents"] = agents

    def set_agent_dag(self, dag: Dict[str, List[str]]):
        """Set the directed acyclic graph for agent dependencies."""
        self.data["agent_specifications"]["agent_dependencies"] = dag

    def to_json(self):
        return self.data

# ==========================================
# 4. AGENT LIBRARY (Agent Definitions) [cite: 335, 343]
# ==========================================
class AgentRegistry:
    """
    Central registry of available agents that can be instantiated.
    Each agent is a specialized AI worker for a specific role.
    """
    
    AGENT_PROFILES = {
        AgentRole.BACKEND_ENGINEER: {
            "role": AgentRole.BACKEND_ENGINEER,
            "description": "Develops backend services, APIs, and business logic",
            "specialties": [AgentSpecialty.AZURE_INFRASTRUCTURE, AgentSpecialty.MICROSERVICES, AgentSpecialty.API_DEVELOPMENT],
            "system_prompt_template": """You are a Backend Engineer Agent in Agentic Nexus.
Your responsibilities:
- Design and implement RESTful APIs and microservices
- Handle authentication, authorization, and security
- Implement business logic and data processing
- Ensure scalability and performance optimization
- Work with Azure services (App Service, Azure Functions, etc.)
- Coordinate with database architect and security engineer

Current Task Context:
{context}

Provide implementation details in JSON format."""
        },
        AgentRole.FRONTEND_ENGINEER: {
            "role": AgentRole.FRONTEND_ENGINEER,
            "description": "Develops user interfaces and frontend applications",
            "specialties": [AgentSpecialty.REACT_FRONTEND, AgentSpecialty.ANGULAR_FRONTEND],
            "system_prompt_template": """You are a Frontend Engineer Agent in Agentic Nexus.
Your responsibilities:
- Design and implement responsive user interfaces
- Handle client-side state management
- Implement user authentication and authorization flows
- Ensure accessibility and performance
- Integrate with backend APIs
- Collaborate with UX/design and backend teams

Current Task Context:
{context}

Provide design and implementation details in JSON format."""
        },
        AgentRole.DATABASE_ARCHITECT: {
            "role": AgentRole.DATABASE_ARCHITECT,
            "description": "Designs database schemas, optimization, and data strategies",
            "specialties": [AgentSpecialty.DATABASE_DESIGN, AgentSpecialty.AZURE_INFRASTRUCTURE],
            "system_prompt_template": """You are a Database Architect Agent in Agentic Nexus.
Your responsibilities:
- Design optimal database schemas (SQL, NoSQL)
- Ensure data integrity and consistency
- Optimize queries and indexing strategies
- Plan backup and disaster recovery
- Ensure compliance with regulations
- Provide data migration strategies

Current Task Context:
{context}

Provide database design specifications in JSON format."""
        },
        AgentRole.SECURITY_ENGINEER: {
            "role": AgentRole.SECURITY_ENGINEER,
            "description": "Ensures security, compliance, and threat mitigation",
            "specialties": [AgentSpecialty.SECURITY_COMPLIANCE, AgentSpecialty.AZURE_INFRASTRUCTURE],
            "system_prompt_template": """You are a Security Engineer Agent in Agentic Nexus.
Your responsibilities:
- Conduct security threat assessments
- Ensure compliance with regulations (GDPR, HIPAA, SOC2, etc.)
- Design authentication and encryption strategies
- Implement secrets management
- Perform security audits and penetration testing recommendations
- Provide security best practices and guidelines

Current Task Context:
{context}

Provide security specifications in JSON format."""
        },
        AgentRole.DEVOPS_ENGINEER: {
            "role": AgentRole.DEVOPS_ENGINEER,
            "description": "Handles infrastructure, deployment, and CI/CD pipelines",
            "specialties": [AgentSpecialty.DEVOPS_CI_CD, AgentSpecialty.AZURE_INFRASTRUCTURE],
            "system_prompt_template": """You are a DevOps Engineer Agent in Agentic Nexus.
Your responsibilities:
- Design CI/CD pipelines and automation
- Configure Azure infrastructure (VMs, containers, AKS)
- Implement monitoring and logging
- Handle deployment strategies and rollback procedures
- Ensure infrastructure security and scalability
- Implement Infrastructure as Code (IaC)

Current Task Context:
{context}

Provide DevOps specifications in JSON format."""
        },
        AgentRole.QA_ENGINEER: {
            "role": AgentRole.QA_ENGINEER,
            "description": "Designs and implements testing strategies and automation",
            "specialties": [AgentSpecialty.TESTING_AUTOMATION],
            "system_prompt_template": """You are a QA Engineer Agent in Agentic Nexus.
Your responsibilities:
- Design comprehensive testing strategies (unit, integration, E2E)
- Implement automated test suites
- Perform performance and load testing
- Ensure code quality and coverage
- Design test data and environments
- Track and manage defects

Current Task Context:
{context}

Provide testing specifications in JSON format."""
        },
        AgentRole.SOLUTION_ARCHITECT: {
            "role": AgentRole.SOLUTION_ARCHITECT,
            "description": "Oversees overall architecture and system design",
            "specialties": [AgentSpecialty.AZURE_INFRASTRUCTURE, AgentSpecialty.MICROSERVICES],
            "system_prompt_template": """You are a Solution Architect Agent in Agentic Nexus.
Your responsibilities:
- Design overall system architecture
- Define technology stack decisions
- Ensure scalability and reliability
- Plan integration between components
- Provide best practices and design patterns
- Coordinate across all agent teams

Current Task Context:
{context}

Provide architecture design in JSON format."""
        },
        AgentRole.API_DESIGNER: {
            "role": AgentRole.API_DESIGNER,
            "description": "Designs API contracts and integration points",
            "specialties": [AgentSpecialty.API_DEVELOPMENT],
            "system_prompt_template": """You are an API Designer Agent in Agentic Nexus.
Your responsibilities:
- Design RESTful API contracts and specifications
- Define OpenAPI/Swagger specifications
- Plan API versioning and deprecation strategies
- Ensure API consistency and best practices
- Design SDK and client libraries
- Plan API rate limiting and throttling

Current Task Context:
{context}

Provide API specifications in JSON format."""
        },
        AgentRole.ML_ENGINEER: {
            "role": AgentRole.ML_ENGINEER,
            "description": "Integrates AI/ML models and manages intelligent features",
            "specialties": [AgentSpecialty.ML_INTEGRATION, AgentSpecialty.AZURE_INFRASTRUCTURE],
            "system_prompt_template": """You are an ML Engineer Agent in Agentic Nexus.
Your responsibilities:
- Design AI/ML integration architecture
- Select and integrate appropriate models (GPT-4o, etc.)
- Design prompt engineering strategies
- Implement ML pipelines and inference endpoints
- Optimize model performance and costs
- Plan monitoring and feedback loops
- Ensure responsible AI practices

Current Task Context:
{context}

Provide ML/AI integration specifications in JSON format."""
        },
    }

    @staticmethod
    def get_agent_profile(role: AgentRole) -> Dict:
        """Retrieve the profile of a specific agent role."""
        return AgentRegistry.AGENT_PROFILES.get(role)

    @staticmethod
    def get_all_roles() -> List[AgentRole]:
        """Get all available agent roles."""
        return list(AgentRegistry.AGENT_PROFILES.keys())

# ==========================================
# 5. DIRECTOR AI (Enhanced) [cite: 335, 343]
# ==========================================
class DirectorAI:
    """
    The Director AI orchestrates project decomposition and agent spawning.
    It transforms user intent into a structured Task Ledger and determines
    which agents should be created and how they should coordinate.
    """
    
    def __init__(self):
        self.client = AzureOpenAI(
            api_key=AZURE_OPENAI_KEY,
            api_version=AZURE_OPENAI_API_VERSION,
            azure_endpoint=AZURE_OPENAI_ENDPOINT
        )

    async def clarify_intent(self, ledger: TaskLedger) -> Dict:
        """
        Translates informal user intent into structured requirements
        with comprehensive project specifications and agent requirements.
        Triggers 'Guardrail Dialogues' if tech choices are risky [cite: 341].
        """
        ledger_schema = json.dumps(ledger.to_json(), indent=2)
        
        system_prompt = f"""You are the Director AI for Agentic Nexus - a no-code/low-code platform for building entire applications from natural language.

Your responsibilities:
1. Analyze user intent and extract all project requirements
2. Decompose the project into tasks that specialized agents can execute
3. Determine which agents are needed and how they should coordinate
4. Define a Directed Acyclic Graph (DAG) of agent dependencies
5. Specify technology stack and architecture patterns
6. Flag any high-risk technical decisions in guardrail_overrides

Available agent roles: {', '.join([r.value for r in AgentRole])}

Return ONLY valid JSON that matches this schema (fill in all applicable fields):
{ledger_schema}

CRITICAL REQUIREMENTS:
required_agents MUST follow this exact structure:
"required_agents": [
  {{
    "role": "backend_engineer",
    "specialty": "api_development",
    "count": 1,
    "dependencies": []
  }}
]
Rules:
- role must match one of the available agent roles
- specialty must match one of the role’s supported specialties
- count must be an integer
- dependencies must be a list (can be empty)
- DO NOT return a list of strings

- Define agent_dependencies as a DAG (agent_id -> [dependent_agent_ids])
- Set parallel_execution_groups for agents that can run simultaneously
- Populate technology_stack with specific tools and frameworks
- Include design_principles, security_requirements, and testing_strategy
- Provide realistic API specifications and database schemas
- Set appropriate non_functional_requirements

RISK ASSESSMENT:
- If the project violates Azure best practices or security guidelines, add to guardrail_overrides
- Include security and compliance considerations in the assessment"""

        logger.info("🧠 Director AI analyzing requirements and planning agent deployment...")
        response = self.client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": ledger.data["user_intent"]}
            ],
            response_format={"type": "json_object"},
            temperature=0.7
        )
        
        updated_data = json.loads(response.choices[0].message.content)
        return updated_data

    async def generate_agent_dag(self, ledger: TaskLedger) -> Tuple[Dict[str, List[str]], List[List[str]]]:
        """
        Generate the dependency DAG and parallel execution groups for agents.
        Returns: (dependency_dag, parallel_groups)
        """
        agents_info = json.dumps(ledger.data["agent_specifications"]["required_agents"], indent=2)
        available_roles = ", ".join([r.value for r in AgentRole])
        
        dag_prompt = f"""Given these agents that need to be created:
{agents_info}

ALLOWED AGENT ROLES ONLY:
{available_roles}

Determine:
1. Which agents depend on which other agents (Directed Acyclic Graph)
2. Which agents can execute in parallel safely

Return JSON with this structure:
{{
    "dependencies": {{
        "agent_role_1": ["agent_role_2", "agent_role_3"],
        "agent_role_2": [],
        ...
    }},
    "parallel_groups": [
        ["agent_role_1", "agent_role_2"],
        ["agent_role_3"],
        ["agent_role_4", "agent_role_5"]
    ]
}}

CRITICAL RULES:
- Use ONLY agent role names from the allowed list above
- Dependencies keys/values must be role names (not instance IDs)
- Dependencies respect logical flow (e.g., database_architect before backend_engineer)
- Parallel groups contain role names of non-dependent agents
- All roles from the input list must be included exactly once
- No role should appear in multiple groups
- Dependencies must be acyclic (no circular dependencies)"""

        response = self.client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": "You are a system architect planning parallel execution."},
                {"role": "user", "content": dag_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.5
        )
        
        dag_data = json.loads(response.choices[0].message.content)
        return dag_data["dependencies"], dag_data["parallel_groups"]

# ==========================================
# 6. SPECIALIZED AGENT CLASSES
# ==========================================
class Agent:
    """
    Base Agent class representing a specialized worker in the system.
    Each agent is spawned with a specific role and operational context.
    NOW: Generates actual production-ready code and communicates with other agents.
    """
    
    def __init__(self, agent_id: str, role: AgentRole, project_context: Dict, comm_hub: AgentCommunicationHub, dependencies: List[str] = None):
        self.agent_id = agent_id
        self.role = role
        self.project_context = project_context
        self.comm_hub = comm_hub
        self.dependencies = dependencies or []
        self.status = "CREATED"
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.outputs = {}
        self.generated_code = {}  # filename -> code content
        self.client = AzureOpenAI(
            api_key=AZURE_OPENAI_KEY,
            api_version=AZURE_OPENAI_API_VERSION,
            azure_endpoint=AZURE_OPENAI_ENDPOINT
        )
        logger.info(f"✨ Agent spawned: {self.agent_id} ({role.value})")

    async def execute(self, task_context: Dict) -> Dict:
        """Execute the agent's task and generate actual production-ready code."""
        self.status = "IN_PROGRESS"
        logger.info(f"🔄 Agent {self.agent_id} generating code...")
        
        profile = AgentRegistry.get_agent_profile(self.role)
        
        # Get messages from other agents
        messages = await self.comm_hub.get_messages(self.agent_id)
        context_from_agents = "\n".join([f"From {m['from']}: {m['content']}" for m in messages]) if messages else "None"
        
        # Get published artifacts from other agents
        artifacts = await self.comm_hub.get_all_artifacts()
        available_artifacts = "\n".join([f"  - {name}" for name in artifacts.keys()]) if artifacts else "None available yet"
        
        system_prompt = profile["system_prompt_template"].format(
            context=json.dumps(task_context, indent=2)
        )
        
        # Modify system prompt to request actual code
        code_generation_prompt = f"""You are a {self.role.value.replace('_', ' ').title()} in Agentic Nexus.

{system_prompt}

YOUR TASK: Generate ACTUAL, PRODUCTION-READY CODE for your role.

DEPENDENCIES COMPLETED:
Your agent dependencies: {', '.join(self.dependencies) if self.dependencies else 'None (you are first)'}

COMMUNICATIONS FROM OTHER AGENTS:
{context_from_agents}

AVAILABLE CODE ARTIFACTS FROM OTHER AGENTS:
{available_artifacts}

INSTRUCTIONS:
1. Generate complete, functional, production-ready code
2. Follow best practices for your domain and role
3. Include proper error handling and documentation
4. Code must be executable and well-structured
5. Create all necessary files for your domain

FORMAT YOUR RESPONSE:
First, provide all code files in this format (one or more):

```filename1.py
<complete code content>
```

```filename2.ts
<complete code content>
```

Then provide metadata:

```json
{{
  "role_summary": "Brief description of what you implemented",
  "files_created": ["filename1.py", "filename2.ts"],
  "key_features": ["feature1", "feature2"],
  "next_steps": "What other agents should do with your code",
  "ready_for": ["list of roles that depend on this"]
}}
```"""
        
        try:
            response = self.client.chat.completions.create(
                model=AZURE_OPENAI_DEPLOYMENT,
                messages=[
                    {"role": "system", "content": "You are an expert code generation specialist. Generate complete, functional, production-ready code."},
                    {"role": "user", "content": code_generation_prompt}
                ],
                temperature=0.7
            )
            
            response_text = response.choices[0].message.content
            
            # Parse code blocks and save locally
            self._parse_and_save_code(response_text)
            
            # Extract JSON metadata and communicate
            self._extract_metadata_and_communicate(response_text)
            
            self.status = "COMPLETED"
            logger.info(f"✅ Agent {self.agent_id} generated {len(self.generated_code)} file(s)")
            return {
                "status": "success",
                "agent_id": self.agent_id,
                "files_generated": list(self.generated_code.keys()),
                "role": self.role.value
            }
            
        except Exception as e:
            self.status = "FAILED"
            logger.error(f"❌ Agent {self.agent_id} failed: {str(e)}")
            return {"error": str(e), "agent_id": self.agent_id, "status": "failed"}
    
    def _parse_and_save_code(self, response_text: str):
        """Parse code blocks from response and save to local files."""
        # Find all code blocks: ```filename.ext\n...\n```
        pattern = r'```([^\n]+)\n(.*?)\n```'
        matches = re.finditer(pattern, response_text, re.DOTALL)
        
        agent_dir = OUTPUT_DIR / "agents" / self.role.value
        agent_dir.mkdir(exist_ok=True, parents=True)
        
        for match in matches:
            filename = match.group(1).strip()
            # Skip JSON blocks (those are metadata)
            if filename.lower() == "json":
                continue
            code_content = match.group(2)
            
            # Save to local file
            filepath = agent_dir / filename
            filepath.parent.mkdir(exist_ok=True, parents=True)
            filepath.write_text(code_content)
            
            self.generated_code[filename] = code_content
            logger.info(f"  📄 Saved: {self.role.value}/{filename}")
            
            # Publish to shared artifacts
            artifact_name = f"{self.role.value}/{filename}"
            self.comm_hub.shared_artifacts[artifact_name] = code_content
    
    def _extract_metadata_and_communicate(self, response_text: str):
        """Extract JSON metadata and send communications to other agents."""
        json_pattern = r'```json\n(.*?)\n```'
        json_match = re.search(json_pattern, response_text, re.DOTALL)
        
        if json_match:
            try:
                metadata = json.loads(json_match.group(1))
                self.outputs = metadata
            except json.JSONDecodeError:
                logger.warning(f"Could not parse JSON metadata from {self.agent_id}")

    def to_dict(self) -> Dict:
        """Convert agent to dictionary for serialization."""
        return {
            "agent_id": self.agent_id,
            "role": self.role.value,
            "status": self.status,
            "created_at": self.created_at,
            "dependencies": self.dependencies,
            "files_generated": list(self.generated_code.keys()),
            "metadata": self.outputs
        }

# ==========================================
# 7. AGENT SPAWNER & ORCHESTRATOR
# ==========================================
class AgentSpawner:
    """
    Responsible for instantiating agents based on task ledger specifications
    and managing their lifecycle in the system.
    """
    
    def __init__(self, cosmos_manager, comm_hub: AgentCommunicationHub):
        self.cosmos_manager = cosmos_manager
        self.comm_hub = comm_hub
        self.agents: Dict[str, Agent] = {}
        self.agent_counter = {}

    async def spawn_agents_from_ledger(self, ledger: TaskLedger) -> Dict[str, Agent]:
        """
        Spawn all required agents based on the task ledger specifications.
        Returns a dictionary mapping agent_id -> Agent instance.
        """
        required_agents = ledger.data["agent_specifications"]["required_agents"]
        logger.info(f"🚀 Spawning {len(required_agents)} agents from task ledger...")
        
        for agent_spec in required_agents:
            role_str = agent_spec.get("role")
            count = agent_spec.get("count", 1)
            
            try:
                role = AgentRole(role_str)
                profile = AgentRegistry.get_agent_profile(role)
                
                if profile is None:
                    logger.warning(f"⚠️  Unknown agent role: {role_str}")
                    continue
                
                for i in range(count):
                    agent_id = f"{role_str}_{i}_{str(uuid.uuid4())[:6]}"
                    agent = Agent(
                        agent_id=agent_id,
                        role=role,
                        project_context={
                            "project_id": ledger.data["project_id"],
                            "project_name": ledger.data.get("project_name", ""),
                            "requirements": ledger.data.get("functional_requirements", []),
                            "tech_stack": ledger.data.get("technology_stack", {})
                        },
                        comm_hub=self.comm_hub,
                        dependencies=agent_spec.get("dependencies", [])
                    )
                    self.agents[agent_id] = agent
                    
            except ValueError as e:
                logger.error(f"❌ Failed to spawn agent with role {role_str}: {e}")
        
        logger.info(f"✅ Successfully spawned {len(self.agents)} agents")
        
        # Create summary of spawned agents
        agent_summary = {}
        for agent_id, agent in self.agents.items():
            if agent.role.value not in agent_summary:
                agent_summary[agent.role.value] = []
            agent_summary[agent.role.value].append(agent_id)
        
        for role, agents_list in agent_summary.items():
            logger.info(f"  📦 {role}: {len(agents_list)} agent(s)")
        
        return self.agents

    async def execute_agents_with_dag(self, dag: Dict[str, List[str]], parallel_groups: List[List[str]]) -> Dict:
        """
        Execute agents respecting their dependencies using the DAG structure.
        
        ARCHITECTURAL TRANSLATION:
        - parallel_groups contains ROLE NAMES (e.g., "backend_engineer")
        - self.agents dict uses INSTANCE IDs (e.g., "backend_engineer_0_xyz")
        - dag uses ROLE NAMES for dependencies
        
        This method translates between abstraction levels:
        Role (DAG) → Multiple Instances (Registry) → Execution
        
        Returns execution results for all agents.
        """
        logger.info("⚙️  Starting agent execution with dependency graph...")
        execution_results = {}
        executed_roles: Set[str] = set()  # Track completed ROLES, not instances
        
        for group in parallel_groups:
            logger.info(f"🔄 Executing parallel group: {group}")
            tasks = []
            group_agents = []
            
            for role_name in group:
                # Find all agent instances matching this role name
                agents_for_role = [
                    agent for agent in self.agents.values()
                    if agent.role.value == role_name
                ]
                
                if not agents_for_role:
                    logger.warning(f"⚠️  No agents found for role: {role_name}")
                    continue
                
                # Check if all dependencies (role-level) are satisfied
                role_dependencies = dag.get(role_name, [])
                if not all(dep_role in executed_roles for dep_role in role_dependencies):
                    logger.warning(f"⚠️  Skipping {role_name} - dependencies not satisfied: {role_dependencies}")
                    continue
                
                # Execute all agent instances with this role in parallel
                for agent in agents_for_role:
                    # Collect outputs from all dependent role instances
                    dependencies_output = {}
                    for dep_role in role_dependencies:
                        dep_agents = [a for a in self.agents.values() if a.role.value == dep_role]
                        # Store outputs from all instances of dependent role
                        dependencies_output[dep_role] = [a.outputs for a in dep_agents]
                    
                    task_context = {
                        "agent_role": role_name,
                        "dependencies_output": dependencies_output
                    }
                    tasks.append(agent.execute(task_context))
                    group_agents.append(agent)
            
            # Execute all tasks in parallel for this group
            if tasks:
                logger.info(f"🚀 Executing {len(tasks)} agent(s) in parallel...")
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for agent, result in zip(group_agents, results):
                    execution_results[agent.agent_id] = result
                    # Mark this role as executed (once per role per group)
                    executed_roles.add(agent.role.value)
        
        logger.info(f"✅ Agent execution completed. Executed roles: {executed_roles}")
        logger.info(f"\n📁 Generated code saved to: {OUTPUT_DIR.absolute()}")
        
        # Print summary of generated files
        logger.info("\n📋 Generated Code Summary:")
        total_files = 0
        for agent in self.agents.values():
            if agent.generated_code:
                logger.info(f"  {agent.agent_id}:")
                for filename in agent.generated_code.keys():
                    logger.info(f"    ✓ {filename}")
                    total_files += 1
        logger.info(f"  Total: {total_files} file(s)")
        
        return execution_results

# ==========================================
# 8. AZURE INFRASTRUCTURE MANAGERS
# ==========================================
class CosmosManager:
    def __init__(self):
        self.client = CosmosClient.from_connection_string(COSMOS_CONNECTION_STR)
        self.db = self.client.create_database_if_not_exists(id=DATABASE_NAME)
        self.ledger_container = self.db.create_container_if_not_exists(
            id=LEDGER_CONTAINER, 
            partition_key=PartitionKey(path="/owner_id")
        )
        self.agent_container = self.db.create_container_if_not_exists(
            id=AGENT_CONTAINER,
            partition_key=PartitionKey(path="/project_id")
        )
        logger.info("✔️  Cosmos DB initialized")

    def save_ledger(self, ledger_data: Dict):
        self.ledger_container.upsert_item(ledger_data)
        logger.info(f"✔️  Ledger {ledger_data['project_id']} persisted to Cosmos DB.")

    def save_agent_registry(self, project_id: str, agents: Dict[str, Agent]):
        """Save agent registry to Cosmos DB for future reference."""
        agent_records = {
            "id": f"agents_{project_id}",
            "project_id": project_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agents": [agent.to_dict() for agent in agents.values()],
            "total_agents": len(agents)
        }
        self.agent_container.upsert_item(agent_records)
        logger.info(f"✔️  Agent registry saved for project {project_id}")

class Orchestrator:
    """Handles Ghost Handshakes and agent coordination via Service Bus [cite: 431, 432]."""
    
    @staticmethod
    async def publish_ghost_handshake(agent_name: str, schema_stub: Dict):
        async with ServiceBusClient.from_connection_string(SERVICE_BUS_STR) as sb:
            async with sb.get_queue_sender(GHOST_HANDSHAKE_QUEUE) as sender:
                message = ServiceBusMessage(json.dumps({
                    "type": "GHOST_HANDSHAKE",
                    "source_agent": agent_name,
                    "stub": schema_stub,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }))
                await sender.send_messages(message)
                logger.info(f"👻 Ghost Handshake published for {agent_name}.")

    @staticmethod
    async def publish_agent_coordination_event(event_type: str, data: Dict):
        """Publish agent coordination events for cross-team communication."""
        async with ServiceBusClient.from_connection_string(SERVICE_BUS_STR) as sb:
            async with sb.get_queue_sender(AGENT_EXECUTION_QUEUE) as sender:
                message = ServiceBusMessage(json.dumps({
                    "event_type": event_type,
                    "data": data,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }))
                await sender.send_messages(message)
                logger.info(f"📢 Coordination event published: {event_type}")

# ==========================================
# 9. MAIN EXECUTION FLOW
# ==========================================
async def main():
    logger.info("🚀 Initializing Agentic Nexus Platform...")
    
    # 1. Capture User Intent
    user_input = """I want to build a multi-tenant SaaS platform for law firms to manage legal documents and case files. 
    
    Requirements:
    - Support for multiple law firm tenants with complete data isolation
    - Document management system (upload, store, organize, retrieve)
    - AI-powered document analysis using GPT-4o (extract key info, summarize contracts)
    - Role-based access control (attorney, paralegal, admin, client)
    - Real-time collaboration features for document annotation
    - Secure document sharing with external parties
    - Full audit logs for compliance (HIPAA, attorney-client privilege protection)
    - Search and indexing for fast retrieval across thousands of documents
    - Mobile-friendly interface
    - Scales to thousands of users across multiple firms
    
    Tech preferences:
    - Azure cloud platform
    - Azure SQL for structured data
    - Azure Blob Storage for document storage
    - GPT-4o for AI features
    - React for frontend
    - Microservices architecture
    
    Timeline: Complete MVP in 3 months"""
    
    owner_id = "user_nexus_2026"
    
    # Initialize systems
    ledger = TaskLedger(user_input, owner_id)
    director = DirectorAI()
    cosmos = CosmosManager()
    comm_hub = AgentCommunicationHub(cosmos)  # Agent communication hub
    spawner = AgentSpawner(cosmos, comm_hub)
    
    try:
        # 2. Director AI analyzes intent and creates comprehensive task ledger
        logger.info("🧠 Director AI analyzing requirements...")
        structured_data = await director.clarify_intent(ledger)
        ledger.data.update(structured_data)
        ledger.add_revision("Initial intent decomposition and agent planning completed.")
        
        logger.info(f"📋 Task Ledger populated with {len(ledger.data.get('agent_specifications', {}).get('required_agents', []))} agent specifications")
        
        # 3. Save the comprehensive task ledger to Cosmos DB
        cosmos.save_ledger(ledger.data)
        
        # 4. Spawn agents based on ledger specifications
        logger.info("\n👥 Spawning specialized agents...")
        agents = await spawner.spawn_agents_from_ledger(ledger)
        
        # 5. Generate agent execution DAG
        logger.info("📊 Building agent dependency graph...")
        dag, parallel_groups = await director.generate_agent_dag(ledger)
        ledger.data["agent_specifications"]["agent_dependencies"] = dag
        ledger.data["agent_specifications"]["parallel_execution_groups"] = parallel_groups
        cosmos.save_ledger(ledger.data)
        
        # 6. Execute agents in parallel respecting dependencies
        logger.info("⚙️  Starting agent execution phase...")
        execution_results = await spawner.execute_agents_with_dag(dag, parallel_groups)
        
        # 7. Save agent registry and results
        cosmos.save_agent_registry(ledger.data["project_id"], agents)
        
        # 8. Publish ghost handshake for backend preparation (pre-emptive stubbing)
        api_stub = {
            "endpoint": "/api/documents",
            "methods": ["GET", "POST", "PUT", "DELETE"],
            "auth": "Bearer JWT",
            "entities": ["Document", "Case", "Organization"]
        }
        await Orchestrator.publish_ghost_handshake("BackendEngineer", api_stub)
        
        # Print comprehensive summary
        logger.info("\n" + "="*70)
        logger.info("✅ AGENTIC NEXUS EXECUTION COMPLETE")
        logger.info("="*70)
        logger.info(f"Project ID: {ledger.data['project_id']}")
        logger.info(f"Project Name: {ledger.data.get('project_name', 'N/A')}")
        logger.info(f"Agents Spawned: {len(agents)}")
        logger.info(f"Agents Executed: {len([a for a in agents.values() if a.status == 'COMPLETED'])}")
        logger.info(f"Total Files Generated: {sum(len(a.generated_code) for a in agents.values())}")
        logger.info("="*70)
        
        
        logger.info("\n📋 --- UPDATED TASK LEDGER SUMMARY ---")
        summary = {
            "project_id": ledger.data["project_id"],
            "project_name": ledger.data.get("project_name", "N/A"),
            "status": ledger.data["status"],
            "agent_count": len(agents),
            "required_agents": ledger.data["agent_specifications"]["required_agents"],
            "technology_stack": ledger.data.get("technology_stack", {}),
            "non_functional_requirements": ledger.data["non_functional_requirements"],
            "parallel_execution_groups": parallel_groups,
            "revision_history": ledger.data["revision_history"]
        }
        logger.info("\n" + json.dumps(summary, indent=2))
        
        logger.info("\n👥 --- AGENT EXECUTION RESULTS ---")
        for agent_id, agent in agents.items():
            status_icon = "✅" if agent.status == "COMPLETED" else "❌"
            files_count = len(agent.generated_code)
            logger.info(f"  {status_icon} {agent_id}: {files_count} file(s) generated")
        
        logger.info(f"\n🏗️  Generated Code Directory Structure:")
        logger.info(f"   📦 {OUTPUT_DIR}/")
        if (OUTPUT_DIR / "agents").exists():
            for role_dir in sorted((OUTPUT_DIR / "agents").iterdir()):
                if role_dir.is_dir():
                    files = list(role_dir.glob("*"))
                    logger.info(f"      📁 {role_dir.name}/ ({len(files)} file(s))")
                    for f in sorted(files):
                        logger.info(f"         └─ {f.name}")
        
        logger.info(f"\n🎉 All agents generated production-ready code!")
        logger.info(f"📂 Review: {OUTPUT_DIR.absolute()}")
        
    except Exception as e:
        logger.error(f"❌ Fatal error in Agentic Nexus: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    asyncio.run(main())