import asyncio
import json
import uuid
import os
import logging
import re
import ast
import subprocess
import random
import hashlib
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Set, Tuple
from enum import Enum
from pathlib import Path
from dotenv import load_dotenv

# --- Azure & AI Imports ---
from azure.cosmos import CosmosClient, PartitionKey
from azure.servicebus.aio import ServiceBusClient, ServiceBusReceiver
from azure.servicebus import ServiceBusMessage
from openai import AzureOpenAI

# --- Deployment Integration ---
from deployment_integration import run_post_generation_deployment

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
EXCHANGE_LOG_CONTAINER = os.getenv("EXCHANGE_LOG_CONTAINER", "AgentExchangeLog")

SERVICE_BUS_STR = os.getenv("SERVICE_BUS_STR")
GHOST_HANDSHAKE_QUEUE = os.getenv("GHOST_HANDSHAKE_QUEUE", "agent-handshake-stubs")
AGENT_COORDINATION_TOPIC = os.getenv("AGENT_COORDINATION_TOPIC", "agent-coordination-events")
AGENT_EXECUTION_QUEUE = os.getenv("AGENT_EXECUTION_QUEUE", "agent-execution-queue")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
MAX_PARALLEL_AGENTS = int(os.getenv("MAX_PARALLEL_AGENTS", "5"))
AGENT_TIMEOUT_SECONDS = int(os.getenv("AGENT_TIMEOUT_SECONDS", "300"))
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
AGENT_TRACE_MODE = os.getenv("AGENT_TRACE_MODE", "summary").strip().lower()
PERSIST_CODE_TO_DB = os.getenv("PERSIST_CODE_TO_DB", "false").strip().lower() == "true"
REQUIRE_OUTPUT_FOR_COMPLETION = os.getenv("REQUIRE_OUTPUT_FOR_COMPLETION", "true").strip().lower() == "true"
SERVICE_BUS_RETRY_MAX = int(os.getenv("SERVICE_BUS_RETRY_MAX", "3"))
SERVICE_BUS_RETRY_BASE_MS = int(os.getenv("SERVICE_BUS_RETRY_BASE_MS", "500"))
ENABLE_SERVICE_BUS_CONSUMER = os.getenv("ENABLE_SERVICE_BUS_CONSUMER", "false").strip().lower() == "true"
RFC_BLOCKING_MODE = os.getenv("RFC_BLOCKING_MODE", "false").strip().lower() == "true"
ENABLE_INTERACTIVE_SHELL = os.getenv("ENABLE_INTERACTIVE_SHELL", "false").strip().lower() == "true"

# Configure logging
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(message)s'  # Simplified format - only show message
)
logger = logging.getLogger(__name__)

VALID_TRACE_MODES = {"off", "summary", "code", "raw"}


def set_agent_trace_mode(mode: str) -> str:
    """Update trace mode at runtime."""
    global AGENT_TRACE_MODE
    normalized = mode.strip().lower()
    if normalized in VALID_TRACE_MODES:
        AGENT_TRACE_MODE = normalized
    return AGENT_TRACE_MODE

# Create output directory for generated code
OUTPUT_DIR = Path("./generated_code")
try:
    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / "agents").mkdir(exist_ok=True)
    (OUTPUT_DIR / "shared").mkdir(exist_ok=True)
except PermissionError:
    # If we don't have write permissions, try with elevated permissions
    os.system(f"mkdir -p {OUTPUT_DIR}/agents {OUTPUT_DIR}/shared 2>/dev/null || true")

# Create logs directory for comprehensive audit trail
LOGS_DIR = Path("./agent_logs")
try:
    LOGS_DIR.mkdir(exist_ok=True)
    (LOGS_DIR / "ai_responses").mkdir(exist_ok=True)
    (LOGS_DIR / "communications").mkdir(exist_ok=True)
    (LOGS_DIR / "requirements").mkdir(exist_ok=True)
except PermissionError:
    # If we don't have write permissions, try with elevated permissions
    os.system(f"mkdir -p {LOGS_DIR}/ai_responses {LOGS_DIR}/communications {LOGS_DIR}/requirements 2>/dev/null || true")

SETUP_PHASE_ROLES: Set[str] = {
    "solution_architect",
    "api_designer",
    "database_architect",
    "security_engineer",
    "devops_engineer",
}

CODING_PHASE_ROLES: Set[str] = {
    "backend_engineer",
    "frontend_engineer",
    "qa_engineer",
    "ml_engineer",
}
MAX_AGENT_ITERATIONS = int(os.getenv("MAX_AGENT_ITERATIONS", "15"))

ROLE_KEYWORD_MAP: Dict[str, Set[str]] = {
    "backend_engineer": {"backend", "api", "service"},
    "frontend_engineer": {"frontend", "ui", "react", "dashboard"},
    "database_architect": {"database", "db", "schema"},
    "devops_engineer": {"devops", "ci/cd", "infra", "terraform", "docker"},
    "security_engineer": {"security", "auth", "encryption"},
    "qa_engineer": {"qa", "test", "testing"},
    "solution_architect": {"architect", "architecture", "solution"},
    "api_designer": {"api designer", "openapi", "swagger"},
    "ml_engineer": {"ml", "ai", "inference", "nlp"},
}

# Role-to-requirements file mapping
ROLE_REQUIREMENTS_MAP: Dict[str, str] = {
    "backend_engineer": "backend_requirements.txt",
    "frontend_engineer": "frontend_requirements.txt",
    "database_architect": "database_requirements.txt",
    "devops_engineer": "devops_requirements.txt",
    "security_engineer": "security_requirements.txt",
    "qa_engineer": "qa_requirements.txt",
    "solution_architect": "architecture_requirements.txt",
    "api_designer": "api_requirements.txt",
    "ml_engineer": "ml_requirements.txt",
}


def extract_target_roles(text: str, all_roles: Set[str]) -> Set[str]:
    """Infer targeted roles from an instruction text."""
    text_l = text.lower()
    matched: Set[str] = set()
    for role in all_roles:
        role_pattern = r"\b" + re.escape(role.replace("_", " ")) + r"s?\b"
        if re.search(role_pattern, text_l):
            matched.add(role)
            continue
        for keyword in ROLE_KEYWORD_MAP.get(role, set()):
            kw_pattern = r"\b" + re.escape(keyword) + r"s?\b"
            if re.search(kw_pattern, text_l):
                matched.add(role)
                break
    return matched if matched else all_roles


# ==========================================
# 1.5. REQUIREMENTS & AUDIT LOGGING [NEW]
# ==========================================
class RequirementsManager:
    """Manages shared requirements files for each role.
    All agents write dependencies/requirements to role-specific files.
    """
    def __init__(self, output_dir: Path = OUTPUT_DIR):
        self.output_dir = output_dir / "shared"
        self.output_dir.mkdir(exist_ok=True)
        self.requirements_dir = self.output_dir / "requirements"
        self.requirements_dir.mkdir(exist_ok=True)
        
        # Initialize requirements files for all roles
        for role, filename in ROLE_REQUIREMENTS_MAP.items():
            req_file = self.requirements_dir / filename
            if not req_file.exists():
                header = f"# {role.replace('_', ' ').title()} Requirements\n"
                header += f"# Auto-generated by agents on {datetime.now(timezone.utc).isoformat()}\n"
                header += f"# All dependencies must be added by agents during execution\n\n"
                req_file.write_text(header)
    
    def add_requirement(self, role: str, requirement: str) -> bool:
        """Add a requirement/dependency to a role's requirements file."""
        filename = ROLE_REQUIREMENTS_MAP.get(role)
        if not filename:
            logger.warning(f"⚠️ Unknown role: {role}")
            return False
        
        req_file = self.requirements_dir / filename
        try:
            content = req_file.read_text()
            if requirement not in content:  # Avoid duplicates
                content += f"{requirement}\n"
                req_file.write_text(content)
                logger.info(f"✅ Added to {filename}: {requirement[:60]}")
            return True
        except Exception as e:
            logger.error(f"❌ Error adding requirement: {e}")
            return False
    
    def get_requirements(self, role: str) -> str:
        """Get all requirements for a role."""
        filename = ROLE_REQUIREMENTS_MAP.get(role)
        if not filename:
            return ""
        
        req_file = self.requirements_dir / filename
        if req_file.exists():
            return req_file.read_text()
        return ""
    
    def get_all_requirements(self) -> Dict[str, str]:
        """Get all requirements across all roles."""
        all_reqs = {}
        for role, filename in ROLE_REQUIREMENTS_MAP.items():
            all_reqs[role] = self.get_requirements(role)
        return all_reqs


class AuditLogger:
    """Comprehensive logging for all agent communications and outputs."""
    def __init__(self, logs_dir: Path = LOGS_DIR):
        self.logs_dir = logs_dir
        self.ai_responses_dir = logs_dir / "ai_responses"
        self.communications_dir = logs_dir / "communications"
        self.requirements_log = logs_dir / "requirements.log"
        
        # Create master log file
        self.master_log = logs_dir / "master_audit.log"
        header = "=" * 80 + "\n"
        header += "AGENTIC NEXUS - COMPREHENSIVE AUDIT LOG\n"
        header += f"Started: {datetime.now(timezone.utc).isoformat()}\n"
        header += "=" * 80 + "\n\n"
        self.master_log.write_text(header)
    
    def log_ai_response(self, agent_id: str, iteration: int, role: str, response: str):
        """Log AI response for an agent."""
        timestamp = datetime.now(timezone.utc).isoformat()
        filename = self.ai_responses_dir / f"{agent_id}_iter{iteration}.log"
        
        content = f"AGENT: {agent_id}\nROLE: {role}\nITERATION: {iteration}\n"
        content += f"TIMESTAMP: {timestamp}\n{'='*80}\n"
        content += f"{response}\n{'='*80}\n\n"
        
        filename.write_text(content)
        self._append_master_log(f"[AI_RESPONSE] {agent_id} iter{iteration}: {len(response)} chars")
    
    def log_handoff(self, from_agent: str, to_agent: str, context: Dict):
        """Log inter-agent handoff."""
        timestamp = datetime.now(timezone.utc).isoformat()
        safe_ts = timestamp[:19].replace(":", "-")
        filename = self.communications_dir / f"handoff_{safe_ts}.log"
        
        content = f"HANDOFF COMMUNICATION\nFROM: {from_agent}\nTO: {to_agent}\n"
        content += f"TIMESTAMP: {timestamp}\nCONTEXT:\n{json.dumps(context, indent=2)}\n"
        content += f"{'='*80}\n\n"
        
        filename.write_text(content)
        self._append_master_log(f"[HANDOFF] {from_agent} → {to_agent}")
    
    def log_blackboard_message(self, sender: str, target_group: str, message: Dict, priority: str):
        """Log blackboard communication."""
        timestamp = datetime.now(timezone.utc).isoformat()
        safe_ts = timestamp[:19].replace(":", "-")
        filename = self.communications_dir / f"blackboard_{safe_ts}.log"
        
        content = f"BLACKBOARD MESSAGE\nSENDER: {sender}\nTARGET GROUP: {target_group}\n"
        content += f"PRIORITY: {priority}\nTIMESTAMP: {timestamp}\n"
        content += f"MESSAGE:\n{json.dumps(message, indent=2)}\n{'='*80}\n\n"
        
        filename.write_text(content)
        self._append_master_log(f"[BLACKBOARD] {sender} → {target_group} ({priority})")
    
    def log_requirement_addition(self, agent_id: str, role: str, requirement: str):
        """Log when an agent adds a requirement."""
        timestamp = datetime.now(timezone.utc).isoformat()
        log_entry = f"[{timestamp}] Agent {agent_id} ({role}): {requirement}\n"
        
        with open(self.requirements_log, "a") as f:
            f.write(log_entry)
        
        self._append_master_log(f"[REQUIREMENT] {agent_id}: {requirement[:50]}")
    
    def _append_master_log(self, entry: str):
        """Append to master audit log."""
        timestamp = datetime.now(timezone.utc).isoformat()
        with open(self.master_log, "a") as f:
            f.write(f"[{timestamp}] {entry}\n")
    
    def get_summary(self) -> str:
        """Get summary of all logged activities."""
        if self.master_log.exists():
            return self.master_log.read_text()
        return ""


class ServiceBusPublisher:
    """Resilient publisher with backoff and lightweight health stats."""

    stats: Dict[str, int] = {
        "publish_success": 0,
        "publish_failures": 0,
        "retry_attempts": 0,
    }

    @staticmethod
    async def publish_json(destination_kind: str, destination_name: str, payload: Dict) -> bool:
        if not SERVICE_BUS_STR:
            return False
        for attempt in range(1, SERVICE_BUS_RETRY_MAX + 1):
            try:
                async with ServiceBusClient.from_connection_string(SERVICE_BUS_STR) as sb:
                    if destination_kind == "topic":
                        async with sb.get_topic_sender(destination_name) as sender:
                            await sender.send_messages(ServiceBusMessage(json.dumps(payload)))
                    else:
                        async with sb.get_queue_sender(destination_name) as sender:
                            await sender.send_messages(ServiceBusMessage(json.dumps(payload)))
                ServiceBusPublisher.stats["publish_success"] += 1
                return True
            except Exception as e:
                ServiceBusPublisher.stats["publish_failures"] += 1
                if attempt < SERVICE_BUS_RETRY_MAX:
                    ServiceBusPublisher.stats["retry_attempts"] += 1
                    backoff = (SERVICE_BUS_RETRY_BASE_MS * (2 ** (attempt - 1))) + random.randint(0, 250)
                    await asyncio.sleep(backoff / 1000.0)
                else:
                    logger.warning(
                        f"⚠️  Service Bus publish failed after {attempt} attempt(s) "
                        f"to {destination_kind}:{destination_name} | {e}"
                    )
                    return False
        return False

    @staticmethod
    def health_snapshot() -> Dict[str, int]:
        return dict(ServiceBusPublisher.stats)

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

class AgentStatus(str, Enum):
    """Enumeration of agent execution statuses for iterative workflows."""
    CREATED = "created"
    IN_PROGRESS = "in_progress"
    WAITING_FOR_RESPONSE = "waiting_for_response"  # Awaiting handoff response
    PAUSED = "paused"  # Awaiting user input
    BLOCKED = "blocked"  # Waiting for dependency
    COMPLETED = "completed"
    FAILED = "failed"

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

class BlackboardPostType(str, Enum):
    """Types of posts on the hierarchical blackboard."""
    GLOBAL_RFC = "global_rfc"      # Everyone sees this
    GROUP_RFC = "group_rfc"        # Only specific group sees this
    HANDOFF = "handoff"            # Direct handoff request
    UPDATE = "update"              # Work progress update
    QUESTION = "question"          # Question for team

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
# 3.5. PERSISTENT BLACKBOARD SYSTEM [NEW]
# ==========================================
class BlackboardSystem:
    """
    Persistent hierarchical blackboard system backed by Cosmos DB.
    Supports global posts (visible to all agents) and group posts (visible to specific roles).
    All posts are immediately persisted to prevent data loss.
    """
    def __init__(self, cosmos_manager, project_id: str):
        self.cosmos_manager = cosmos_manager
        self.project_id = project_id
        self.local_cache: List[Dict] = []
        self.local_cache_by_role: Dict[str, List[Dict]] = {}

    async def post_to_board(self, sender_id: str, target_group: str, content: str, 
                           post_type: BlackboardPostType, role_of_sender: str = None) -> str:
        """Post a message to the blackboard (global or group-specific)."""
        post_id = str(uuid.uuid4())[:8]
        post = {
            "id": post_id,
            "project_id": self.project_id,
            "sender_id": sender_id,
            "sender_role": role_of_sender,
            "target_group": target_group,
            "content": content,
            "post_type": post_type.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "visible_to_roles": [target_group] if target_group != "all" else []
        }
        
        self.local_cache.append(post)
        if target_group not in self.local_cache_by_role:
            self.local_cache_by_role[target_group] = []
        self.local_cache_by_role[target_group].append(post)
        
        try:
            if self.cosmos_manager:
                await self.cosmos_manager.save_blackboard_post(self.project_id, post)
        except Exception as e:
            logger.warning(f"⚠️  Could not persist blackboard post to Cosmos DB: {e}")
        
        return post_id

    async def read_board(self, agent_role: str) -> str:
        """Fetch posts relevant to this agent's role."""
        relevant_posts = [
            p for p in self.local_cache
            if p["target_group"] == "all" or p["target_group"] == agent_role
        ]
        
        if not relevant_posts:
            return "📋 Blackboard is currently empty."
        
        board_text = "\n" + "="*70 + "\n📋 BLACKBOARD\n" + "="*70 + "\n"
        for p in sorted(relevant_posts, key=lambda x: x["timestamp"]):
            scope = "🌍 GLOBAL" if p["target_group"] == "all" else f"👥 {p['target_group'].upper()}"
            board_text += f"[{p['post_type'].upper()}] {scope} | {p['sender_id']}: {p['content'][:150]}\n"
        board_text += "="*70
        return board_text

    async def get_critical_posts(self, agent_role: str) -> List[Dict]:
        """Get high-priority posts (HANDOFF, QUESTION)."""
        return [
            p for p in self.local_cache
            if (p["target_group"] == "all" or p["target_group"] == agent_role)
            and p["post_type"] in ["handoff", "question"]
        ]

# ==========================================
# 3.6. PLACEHOLDER DETECTION SYSTEM [NEW]
# ==========================================
class PlaceholderDetector:
    """
    Detects if the LLM returned CRITICAL placeholder code stubs.
    Softened to allow '...' in comments (valid for ellipsis patterns).
    Only flags REAL stubs like [Your code here] or pass-only functions.
    """
    
    # CRITICAL stubs that indicate incomplete code (not '...')
    CRITICAL_PLACEHOLDERS = [
        "<complete",
        "<your",
        "<implementation",
        "[Your code here]",
        "[Implementation here]",
        "[your code here]",
        "[implementation here]",
    ]
    
    @staticmethod
    def check_for_placeholders(response_text: str) -> Tuple[bool, str]:
        """
        Detect if the LLM returned CRITICAL placeholder code.
        Allows '...' in comments. Only blocks real stubs.
        Returns: (has_placeholder, error_message)
        """
        code_blocks = re.findall(r'```([a-z]*)\n(.*?)```', response_text, re.DOTALL)
        
        for lang, code in code_blocks:
            code_lower = code.lower()
            
            # Only check for CRITICAL placeholders (not '...')
            for critical in PlaceholderDetector.CRITICAL_PLACEHOLDERS:
                if critical.lower() in code_lower:
                    return True, f"Critical placeholder found: '{critical}'"
        
        return False, ""
    
    @staticmethod
    def get_placeholder_error_message() -> str:
        """Generate error message for placeholder code."""
        return """❌ ERROR: Code has critical placeholders.

REQUIREMENT:
- Generate complete, functional code
- No stubs: [Your code here], <complete>, <implementation>
- Every function needs actual working code
- Comments with '...' are OK
- Provide best attempt if unsure

ACTION: Regenerate with full implementation next iteration."""

# ==========================================
# 3.7. INTERACTIVE SHELL [NEW]
# ==========================================
async def run_interactive_shell(
    agents: Dict[str, 'Agent'],
    ledger: 'TaskLedger',
    blackboard_manager: 'BlackboardManager',
    swarm_orchestrator: 'SwarmOrchestrator',
    project_id: str,
):
    """
    Interactive shell for real-time feedback and control of agents.
    Runs at the end of main() to allow user to interact with the system.
    
    Commands:
    - status: Show all agents and their progress
    - blackboard: Display recent central blackboard posts
    - ask [q]: Post instruction and auto-rerun targeted agents
    - rerun [role|agent_id]: Explicitly rerun selected agents
    - trace [off|summary|code|raw]: Set runtime trace mode
    - exit: Exit the interactive shell
    """
    logger.info("\n🎮 Entering interactive mode (press Ctrl+C to exit)...\n")
    
    while True:
        try:
            user_input = (await asyncio.to_thread(input, "[NEXUS] > ")).strip()
            command_l = user_input.lower()
            
            if not user_input:
                continue
            
            elif command_l in {"exit", "quit"}:
                logger.info("\n👋 Exiting Agentic Nexus. Goodbye!")
                break
            
            elif command_l == "status":
                logger.info("\n" + "="*70)
                logger.info("📊 SWARM STATUS REPORT")
                logger.info("="*70)
                completed = len([a for a in agents.values() if a.status == AgentStatus.COMPLETED])
                waiting = len([a for a in agents.values() if a.status == AgentStatus.WAITING_FOR_RESPONSE])
                paused = len([a for a in agents.values() if a.status == AgentStatus.PAUSED])
                failed = len([a for a in agents.values() if a.status == AgentStatus.FAILED])
                total_files = sum(len(a.generated_code) for a in agents.values())
                logger.info(f"Agents Completed: {completed}/{len(agents)}")
                logger.info(f"Waiting: {waiting} | Paused: {paused} | Failed: {failed}")
                logger.info(f"Total Files Generated: {total_files}")
                logger.info(f"Trace Mode: {AGENT_TRACE_MODE}")
                logger.info(f"Project ID: {project_id}")
                logger.info(f"Service Bus Health: {ServiceBusPublisher.health_snapshot()}")
                for agent_id, agent in agents.items():
                    if agent.status == AgentStatus.COMPLETED:
                        status_icon = "✅"
                    elif agent.status == AgentStatus.IN_PROGRESS:
                        status_icon = "⏳"
                    elif agent.status == AgentStatus.WAITING_FOR_RESPONSE:
                        status_icon = "📨"
                    elif agent.status == AgentStatus.PAUSED:
                        status_icon = "⏸️"
                    elif agent.status == AgentStatus.FAILED:
                        status_icon = "❌"
                    else:
                        status_icon = "❓"
                    logger.info(f"  {status_icon} {agent_id}: {agent.status.value} ({len(agent.generated_code)} files)")
                logger.info("="*70 + "\n")
            
            elif command_l == "blackboard":
                central = blackboard_manager.central_blackboard.messages[-20:]
                if not central:
                    logger.info("\n📋 Blackboard is currently empty.\n")
                else:
                    logger.info("\n" + "="*70)
                    logger.info("📋 TEAM CENTRAL BLACKBOARD (LAST 20)")
                    logger.info("="*70)
                    for msg in central:
                        title = str(msg.get("message", {}).get("title", "untitled"))
                        sender = msg.get("from_agent", "unknown")
                        priority = msg.get("priority", "normal")
                        logger.info(f"[{priority.upper()}] {sender}: {title} (ID: {msg.get('id')})")
                    logger.info("="*70 + "\n")
            
            elif command_l.startswith("ask "):
                question = user_input[4:].strip()
                role_set = set(agent.role.value for agent in agents.values())
                target_roles = sorted(extract_target_roles(question, role_set))
                logger.info(f"\n❓ Broadcasting instruction to team: {question}")
                await blackboard_manager.broadcast_to_central(
                    "user",
                    {
                        "title": f"User instruction ({', '.join(target_roles)})",
                        "body": question,
                        "message_type": "user_instruction",
                        "target_roles": target_roles,
                        "requires_action": True,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                    priority="critical",
                )
                rerun_result = await swarm_orchestrator.rerun_agents(
                    agents=agents,
                    task_context=ledger.data,
                    timeout_per_agent=AGENT_TIMEOUT_SECONDS,
                    instruction=question,
                    target_roles=set(target_roles),
                )
                logger.info(
                    "✅ Instruction routed. "
                    f"matched={rerun_result.get('matched_agents', 0)}, "
                    f"scheduled={rerun_result.get('scheduled_agents', 0)}.\n"
                )

            elif command_l.startswith("rerun "):
                selector = user_input[6:].strip()
                rerun_result = await swarm_orchestrator.rerun_agents(
                    agents=agents,
                    task_context=ledger.data,
                    timeout_per_agent=AGENT_TIMEOUT_SECONDS,
                    instruction=f"Manual rerun requested: {selector}",
                    selector=selector,
                )
                logger.info(
                    f"\n▶️ Rerun requested for '{selector}'. "
                    f"matched={rerun_result.get('matched_agents', 0)}, "
                    f"scheduled={rerun_result.get('scheduled_agents', 0)}.\n"
                )

            elif command_l.startswith("trace "):
                mode = user_input[6:].strip().lower()
                selected = set_agent_trace_mode(mode)
                logger.info(f"\n🧭 Trace mode set to: {selected}\n")

            elif command_l.startswith("agents "):
                role_filter = user_input[7:].strip().lower()
                logger.info("")
                for agent_id, agent in agents.items():
                    if role_filter in {agent.role.value, agent_id.lower()}:
                        logger.info(f"  {agent_id}: {agent.role.value} | {agent.status.value}")
                logger.info("")
            
            else:
                logger.info(
                    "\n❓ Unknown command. Type 'status', 'blackboard', 'ask [q]', "
                    "'rerun [role|agent_id]', 'trace [off|summary|code|raw]', "
                    "'agents [role]', or 'exit'.\n"
                )
        
        except KeyboardInterrupt:
            logger.info("\n\n👋 Exiting interactive mode.")
            break
        except Exception as e:
            logger.error(f"\n❌ Error in interactive shell: {e}\n")

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
- Write production-ready backend code (Python, Node.js, Java, etc.)
- Handle authentication, authorization, and security
- Implement business logic and data processing
- Ensure scalability and performance optimization
- Work with Azure services (App Service, Azure Functions, etc.)
- Coordinate with database architect and security engineer

Current Task Context:
{context}

CODE OUTPUT MODES (Choose based on context):

MODE 1: FULL FILE (for new files or complete rewrites)
```filename.py
<complete working code>
```

MODE 2: SEARCH/REPLACE (for modifying existing files) ⭐ PREFERRED
<<<<<<< SEARCH
filename.py
    def existing_function():
        return "old"
=======
    def existing_function():
        return "new"The problem is that the individual agent profiles' prompts are being overridden/supplemented, but they lack the critical MODE 2 (SEARCH/REPLACE) instructions. Let me update all of these to include the dual-mode guidance:


>>>>>>> REPLACE

For first iteration: Use MODE 1 (full files)
For subsequent iterations: Use MODE 2 (atomic edits only)
MODE 2 is faster, more precise, and reduces token waste."""
        },
        AgentRole.FRONTEND_ENGINEER: {
            "role": AgentRole.FRONTEND_ENGINEER,
            "description": "Develops user interfaces and frontend applications",
            "specialties": [AgentSpecialty.REACT_FRONTEND, AgentSpecialty.ANGULAR_FRONTEND],
            "system_prompt_template": """You are a Frontend Engineer Agent in Agentic Nexus.
Your responsibilities:
- Design and implement responsive user interfaces
- Write production-ready React/Vue/Angular components
- Handle client-side state management
- Implement user authentication and authorization flows
- Ensure accessibility and performance
- Integrate with backend APIs
- Collaborate with UX/design and backend teams

⚠️  CRITICAL: FILE NAMING STANDARDS
When creating frontend files, use these EXACT filenames:
- Main HTML page: index.html (NOT "html", "index", "page", etc.)
- React components: ComponentName.jsx or ComponentName.tsx
- Styles: styles.css or component-name.module.css
- Configuration: config.js, vite.config.js, tailwind.config.js
- Pages: pages/PageName.jsx for multi-page apps
- Assets: images/, fonts/, assets/ directories

ALWAYS include proper file extensions (.html, .jsx, .css, .json, etc.)
DO NOT create files without extensions (e.g., "html" → "index.html")

Current Task Context:
{context}

CODE OUTPUT MODES (Choose based on context):

MODE 1: FULL FILE (for new files or complete rewrites)
```index.html
<!DOCTYPE html>
<html>...
</html>
```

MODE 2: SEARCH/REPLACE (for modifying existing files) ⭐ PREFERRED
<<<<<<< SEARCH
index.html
    <title>Old Title</title>
=======
    <title>New Title</title>
>>>>>>> REPLACE

For first iteration: Use MODE 1 (full files) with CORRECT filenames
For subsequent iterations: Use MODE 2 (atomic edits only)
MODE 2 is faster, more precise, and reduces token waste."""
        },
        AgentRole.DATABASE_ARCHITECT: {
            "role": AgentRole.DATABASE_ARCHITECT,
            "description": "Designs database schemas, optimization, and data strategies",
            "specialties": [AgentSpecialty.DATABASE_DESIGN, AgentSpecialty.AZURE_INFRASTRUCTURE],
            "system_prompt_template": """You are a Database Architect Agent in Agentic Nexus.
Your responsibilities:
- Design optimal database schemas (SQL, NoSQL)
- Write SQL DDL statements and migration scripts
- Ensure data integrity and consistency
- Optimize queries and indexing strategies
- Plan backup and disaster recovery
- Ensure compliance with regulations
- Provide data migration strategies

Current Task Context:
{context}

CODE OUTPUT MODES (Choose based on context):

MODE 1: FULL FILE (for new files or complete schema rewrites)
```schema.sql
CREATE TABLE users (id INT PRIMARY KEY, name VARCHAR(255));
CREATE INDEX idx_user_name ON users(name);
```

MODE 2: SEARCH/REPLACE (for modifying existing schemas) ⭐ PREFERRED
<<<<<<< SEARCH
schema.sql
    CREATE TABLE users (
        id INT PRIMARY KEY,
        name VARCHAR(255)
    );
=======
    CREATE TABLE users (
        id INT PRIMARY KEY,
        name VARCHAR(255),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
>>>>>>> REPLACE

For first iteration: Use MODE 1 (full files)
For subsequent iterations: Use MODE 2 (atomic edits only)
MODE 2 is faster, more precise, and reduces token waste."""
        },
        AgentRole.SECURITY_ENGINEER: {
            "role": AgentRole.SECURITY_ENGINEER,
            "description": "Ensures security, compliance, and threat mitigation",
            "specialties": [AgentSpecialty.SECURITY_COMPLIANCE, AgentSpecialty.AZURE_INFRASTRUCTURE],
            "system_prompt_template": """You are a Security Engineer Agent in Agentic Nexus.
Your responsibilities:
- Conduct security threat assessments
- Implement authentication and encryption strategies
- Write security configuration code
- Ensure compliance with regulations (GDPR, HIPAA, SOC2, etc.)
- Design secrets management
- Perform security audits and recommendations
- Provide security best practices and guidelines

Current Task Context:
{context}

CODE OUTPUT MODES (Choose based on context):

MODE 1: FULL FILE (for new files or complete security implementations)
```security_config.py
from cryptography.fernet import Fernet
<complete security configuration code>
```

MODE 2: SEARCH/REPLACE (for modifying existing security code) ⭐ PREFERRED
<<<<<<< SEARCH
security_config.py
    def validate_token(token):
        return True
=======
    def validate_token(token):
        from jwt import decode
        return decode(token, SECRET_KEY, algorithms=['HS256'])
>>>>>>> REPLACE

For first iteration: Use MODE 1 (full files)
For subsequent iterations: Use MODE 2 (atomic edits only)
MODE 2 is faster, more precise, and reduces token waste."""
        },
        AgentRole.DEVOPS_ENGINEER: {
            "role": AgentRole.DEVOPS_ENGINEER,
            "description": "Handles infrastructure, deployment, and CI/CD pipelines",
            "specialties": [AgentSpecialty.DEVOPS_CI_CD, AgentSpecialty.AZURE_INFRASTRUCTURE],
            "system_prompt_template": """You are a DevOps Engineer Agent in Agentic Nexus.
Your responsibilities:
- Design CI/CD pipelines and automation scripts
- Configure Azure infrastructure (VMs, containers, AKS)
- Write Infrastructure as Code (IaC) configurations
- Implement monitoring and logging
- Handle deployment strategies and rollback procedures
- Ensure infrastructure security and scalability
- Optimize cloud costs

Current Task Context:
{context}

CODE OUTPUT MODES (Choose based on context):

MODE 1: FULL FILE (for new files or complete infrastructure configurations)
```docker-compose.yml
version: '3'
services:
  app:
    image: myapp:latest
```

MODE 2: SEARCH/REPLACE (for modifying existing infrastructure) ⭐ PREFERRED
<<<<<<< SEARCH
docker-compose.yml
    services:
      app:
        image: myapp:latest
=======
    services:
      app:
        image: myapp:latest
        environment:
          - LOG_LEVEL=DEBUG
>>>>>>> REPLACE

For first iteration: Use MODE 1 (full files)
For subsequent iterations: Use MODE 2 (atomic edits only)
MODE 2 is faster, more precise, and reduces token waste."""
        },
        AgentRole.QA_ENGINEER: {
            "role": AgentRole.QA_ENGINEER,
            "description": "Designs and implements testing strategies and automation",
            "specialties": [AgentSpecialty.TESTING_AUTOMATION],
            "system_prompt_template": """You are a QA Engineer Agent in Agentic Nexus.
Your responsibilities:
- Design comprehensive testing strategies (unit, integration, E2E)
- Write automated test suites and test code
- Perform performance and load testing
- Ensure code quality and coverage
- Design test data and environments
- Track and manage defects

Current Task Context:
{context}

CODE OUTPUT MODES (Choose based on context):

MODE 1: FULL FILE (for new test files or complete test suites)
```test_unit.py
import unittest
class TestMyFunction(unittest.TestCase):
    def test_basic(self):
        self.assertTrue(True)
```

MODE 2: SEARCH/REPLACE (for modifying existing tests) ⭐ PREFERRED
<<<<<<< SEARCH
test_unit.py
    class TestMyFunction(unittest.TestCase):
        def test_basic(self):
            self.assertTrue(True)
=======
    class TestMyFunction(unittest.TestCase):
        def test_basic(self):
            self.assertTrue(True)
        def test_advanced(self):
            self.assertEqual(1 + 1, 2)
>>>>>>> REPLACE

For first iteration: Use MODE 1 (full files)
For subsequent iterations: Use MODE 2 (atomic edits only)
MODE 2 is faster, more precise, and reduces token waste."""
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
- Create architecture diagrams and documentation

Current Task Context:
{context}

CODE OUTPUT MODES (Choose based on context):

MODE 1: FULL FILE (for new architecture documentation)
```architecture.md
# System Architecture
## Overview
Complete microservices architecture with database and API layer.
```

MODE 2: SEARCH/REPLACE (for updating existing documentation) ⭐ PREFERRED
<<<<<<< SEARCH
architecture.md
# System Architecture
=======
# System Architecture v2.0
Updated with Kubernetes orchestration.
>>>>>>> REPLACE

For first iteration: Use MODE 1 (full files)
For subsequent iterations: Use MODE 2 (atomic edits only)
MODE 2 is faster, more precise, and reduces token waste."""
        },
        AgentRole.API_DESIGNER: {
            "role": AgentRole.API_DESIGNER,
            "description": "Designs API contracts and integration points",
            "specialties": [AgentSpecialty.API_DEVELOPMENT],
            "system_prompt_template": """You are an API Designer Agent in Agentic Nexus.
Your responsibilities:
- Design RESTful API contracts and specifications
- Write OpenAPI/Swagger specifications
- Plan API versioning and deprecation strategies
- Ensure API consistency and best practices
- Design SDK and client libraries
- Plan API rate limiting and throttling

Current Task Context:
{context}

CODE OUTPUT MODES (Choose based on context):

MODE 1: FULL FILE (for new API specifications)
```openapi.yaml
openapi: 3.0.0
info:
  title: My API
  version: 1.0.0
paths:
  /users:
    get:
      summary: List users
```

MODE 2: SEARCH/REPLACE (for updating existing API specs) ⭐ PREFERRED
<<<<<<< SEARCH
openapi.yaml
  /users:
    get:
      summary: List users
=======
  /users:
    get:
      summary: List users
      parameters:
        - name: limit
          in: query
          schema:
            type: integer
>>>>>>> REPLACE

For first iteration: Use MODE 1 (full files)
For subsequent iterations: Use MODE 2 (atomic edits only)
MODE 2 is faster, more precise, and reduces token waste."""
        },
        AgentRole.ML_ENGINEER: {
            "role": AgentRole.ML_ENGINEER,
            "description": "Integrates AI/ML models and manages intelligent features",
            "specialties": [AgentSpecialty.ML_INTEGRATION, AgentSpecialty.AZURE_INFRASTRUCTURE],
            "system_prompt_template": """You are an ML Engineer Agent in Agentic Nexus.
Your responsibilities:
- Design AI/ML integration architecture
- Select and integrate appropriate models (GPT-4o, etc.)
- Write ML pipeline code and inference endpoints
- Design prompt engineering strategies
- Implement model training and evaluation
- Optimize model performance and costs
- Ensure responsible AI practices
- Plan monitoring and feedback loops

Current Task Context:
{context}

CODE OUTPUT MODES (Choose based on context):

MODE 1: FULL FILE (for new ML pipeline code)
```ml_pipeline.py
import azure.ai
from azure.openai import AzureOpenAI
client = AzureOpenAI()
```

MODE 2: SEARCH/REPLACE (for updating existing ML code) ⭐ PREFERRED
<<<<<<< SEARCH
ml_pipeline.py
    client = AzureOpenAI()
=======
    client = AzureOpenAI(
        api_key=os.getenv('AZURE_OPENAI_KEY'),
        api_version='2024-02-01'
    )
>>>>>>> REPLACE

For first iteration: Use MODE 1 (full files)
For subsequent iterations: Use MODE 2 (atomic edits only)
MODE 2 is faster, more precise, and reduces token waste."""
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
# 4.5. CHECKPOINT MANAGER (Stateful Memory) [NEW]
# ==========================================
class CheckpointManager:
    """
    Manages agent state persistence across iterations.
    Enables agents to pause, save state, and resume from checkpoints.
    """
    def __init__(self, cosmos_manager):
        self.cosmos = cosmos_manager
        self.checkpoints: Dict[str, Dict] = {}  # agent_id -> checkpoint data
    
    async def save_checkpoint(self, agent_id: str, state: Dict):
        """Save agent state to Cosmos DB for resumption."""
        checkpoint = {
            "id": f"checkpoint_{agent_id}_{datetime.now(timezone.utc).timestamp()}",
            "agent_id": agent_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "state": state,
            "message_history": state.get("message_history", []),
            "context": state.get("context", {}),
            "status": state.get("status", "paused")
        }
        self.checkpoints[agent_id] = checkpoint
        logger.info(f"💾 Checkpoint saved for {agent_id}")
    
    async def load_checkpoint(self, agent_id: str) -> Optional[Dict]:
        """Load most recent checkpoint for an agent."""
        if agent_id in self.checkpoints:
            return self.checkpoints[agent_id]
        logger.info(f"📂 No checkpoint found for {agent_id}")
        return None
    
    async def list_checkpoints(self, agent_id: str) -> List[Dict]:
        """List all checkpoints for an agent."""
        return [self.checkpoints[agent_id]] if agent_id in self.checkpoints else []

# ==========================================
# 4.6. HANDOFF & RFC MECHANISM [NEW]
# ==========================================
class Handoff:
    """
    Represents a request from one agent to another for collaboration.
    Enables dynamic task transfer and delegation.
    """
    def __init__(self, from_agent: str, to_agent: str, context: Dict, required_by: Optional[float] = None):
        self.id = str(uuid.uuid4())[:8]
        self.from_agent = from_agent
        self.to_agent = to_agent
        self.context = context
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.required_by = required_by  # Unix timestamp when result is needed
        self.status = "PENDING"
        self.result = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "context": self.context,
            "created_at": self.created_at,
            "required_by": self.required_by,
            "status": self.status,
            "result": self.result
        }

class RequestForComment:
    """
    Shared workspace item for agents to post requests and feedback.
    Enables asynchronous, non-blocking collaboration.
    """
    def __init__(self, author: str, title: str, description: str, tags: List[str] = None):
        self.id = str(uuid.uuid4())[:8]
        self.author = author
        self.title = title
        self.description = description
        self.tags = tags or []
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.comments: List[Dict] = []  # {from_agent, content, timestamp}
        self.status = "OPEN"
        self.decisions: Dict[str, str] = {}  # key -> decision made
    
    def add_comment(self, from_agent: str, content: str):
        """Add a comment to the RFC."""
        self.comments.append({
            "from_agent": from_agent,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "author": self.author,
            "title": self.title,
            "description": self.description,
            "tags": self.tags,
            "created_at": self.created_at,
            "comments": self.comments,
            "status": self.status,
            "decisions": self.decisions
        }

class RoleResolver:
    """
    Resolves role names to actual agent instances.
    Enables handoffs using role names instead of specific instance IDs.
    Provides load balancing across multiple instances of the same role.
    """
    def __init__(self, agents: Dict[str, 'Agent']):
        self.agents = agents
        self.agent_workload: Dict[str, int] = {agent_id: 0 for agent_id in agents.keys()}
    
    def resolve_role_to_agent(self, role_name: str) -> Optional[str]:
        """
        Find the best available agent instance for a given role.
        Returns agent_id of the least-busy agent, or None if role not found.
        """
        candidates = [
            agent_id for agent_id, agent in self.agents.items()
            if agent.role.value == role_name
        ]
        
        if not candidates:
            logger.warning(f"⚠️  No agents found for role: {role_name}")
            return None
        
        # Return agent with lowest workload
        best_agent = min(candidates, key=lambda aid: self.agent_workload.get(aid, 0))
        logger.info(f"✅ Role '{role_name}' resolved to agent {best_agent}")
        return best_agent
    
    def mark_workload(self, agent_id: str, delta: int = 1):
        """Update workload for an agent (delta can be positive or negative)."""
        if agent_id in self.agent_workload:
            self.agent_workload[agent_id] += delta

class CollaborationBus:
    """
    Shared message bus for agents to post handoffs and RFCs.
    Enables dynamic, non-blocking inter-agent communication.
    Now supports role-based handoff routing via RoleResolver.
    Persists all communications to Cosmos DB for audit trails.
    """
    def __init__(self, role_resolver: Optional[RoleResolver] = None, cosmos_manager=None, project_id: str = None):
        self.handoffs: Dict[str, Handoff] = {}
        self.rfcs: Dict[str, RequestForComment] = {}
        self.pending_for_agent: Dict[str, List[str]] = {}  # agent_id -> [handoff_ids]
        self.role_resolver = role_resolver
        self.cosmos_manager = cosmos_manager  # For persisting communications
        self.project_id = project_id  # For organizing in Cosmos DB
    
    def set_role_resolver(self, role_resolver: RoleResolver):
        """Set the role resolver after initialization."""
        self.role_resolver = role_resolver
    
    async def post_handoff(self, handoff: Handoff) -> str:
        """
        Post a handoff request to the bus AND Azure Service Bus.
        Automatically resolves role names to agent instances if needed.
        """
        target_agent_id = handoff.to_agent
        
        # Check if target_agent is a role name (not a specific instance ID)
        if self.role_resolver and "_" not in handoff.to_agent:
            # Likely a role name like "backend_engineer"
            resolved_id = self.role_resolver.resolve_role_to_agent(handoff.to_agent)
            if resolved_id:
                target_agent_id = resolved_id
                logger.info(f"🔄 Resolved role '{handoff.to_agent}' to instance '{target_agent_id}'")
            else:
                logger.error(f"❌ Could not resolve role '{handoff.to_agent}' to any agent instance")
                return None
        
        # Update handoff with resolved target
        handoff.to_agent = target_agent_id
        
        self.handoffs[handoff.id] = handoff
        if target_agent_id not in self.pending_for_agent:
            self.pending_for_agent[target_agent_id] = []
        self.pending_for_agent[target_agent_id].append(handoff.id)
        
        # Mark workload
        if self.role_resolver:
            self.role_resolver.mark_workload(target_agent_id, delta=1)
        
        logger.info(f"🤝 [HANDOFF] {handoff.from_agent[:20]} → {target_agent_id[:20]} | Status: {handoff.status} (ID: {handoff.id})")
        
        # Persist to Cosmos DB if available
        if self.cosmos_manager and self.project_id:
            try:
                self.cosmos_manager.save_handoff(self.project_id, handoff)
            except Exception as e:
                logger.warning(f"⚠️  Could not persist handoff to Cosmos DB: {e}")
        
        # Publish to Azure Service Bus for cross-service visibility (best effort)
        published = await ServiceBusPublisher.publish_json(
            "topic",
            "agent-handoff-topic",
            {
                "handoff_id": handoff.id,
                "from_agent": handoff.from_agent,
                "to_agent": target_agent_id,
                "title": handoff.context.get("title", "handoff"),
                "status": handoff.status,
                "context": handoff.context,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        if not published:
            logger.info("ℹ️  Continuing without Service Bus handoff publish (local/Cosmos persisted)")
        
        return handoff.id
    
    async def get_pending_handoffs(self, agent_id: str) -> List[Handoff]:
        """Get all pending handoffs for an agent."""
        handoff_ids = self.pending_for_agent.get(agent_id, [])
        handoffs = [self.handoffs[hid] for hid in handoff_ids if hid in self.handoffs]
        return handoffs
    
    async def complete_handoff(self, handoff_id: str, result: Dict):
        """Mark a handoff as complete with result."""
        if handoff_id in self.handoffs:
            self.handoffs[handoff_id].status = "COMPLETED"
            self.handoffs[handoff_id].result = result
            logger.info(f"✅ Handoff completed: {handoff_id}")
    
    async def post_rfc(self, rfc: RequestForComment) -> str:
        """Post an RFC to the shared workspace AND Azure Service Bus."""
        self.rfcs[rfc.id] = rfc
        logger.info(f"📝 [RFC] {rfc.title[:50]} (Author: {rfc.author[:20]}, ID: {rfc.id})")
        
        # Persist to Cosmos DB if available
        if self.cosmos_manager and self.project_id:
            try:
                self.cosmos_manager.save_rfc(self.project_id, rfc)
            except Exception as e:
                logger.warning(f"⚠️  Could not persist RFC to Cosmos DB: {e}")
        
        # Publish to Azure Service Bus for cross-service visibility (best effort)
        published = await ServiceBusPublisher.publish_json(
            "topic",
            "agent-rfc-topic",
            {
                "rfc_id": rfc.id,
                "author": rfc.author,
                "title": rfc.title,
                "description": rfc.description[:500],
                "tags": rfc.tags,
                "timestamp": rfc.created_at,
            },
        )
        if not published:
            logger.info("ℹ️  Continuing without Service Bus RFC publish (local/Cosmos persisted)")
        
        return rfc.id
    
    async def get_rfcs_for_agent(self, agent_id: str, tag: str = None) -> List[RequestForComment]:
        """Get RFCs relevant to an agent (optionally filtered by tag)."""
        rfcs = list(self.rfcs.values())
        if tag:
            rfcs = [r for r in rfcs if tag in r.tags]
        # Return RFCs authored by or mentioning this agent
        return rfcs

# ==========================================
# 4.7. BLACKBOARD SYSTEM (Azure Service Bus) [NEW]
# ==========================================
class Blackboard:
    """
    Shared communication board for agents to post messages.
    Uses Azure Service Bus Topics for pub/sub communication.
    """
    def __init__(self, topic_name: str, subscription_name: str = None):
        self.topic_name = topic_name
        self.subscription_name = subscription_name or f"sub_{topic_name}_{str(uuid.uuid4())[:6]}"
        self.messages: List[Dict] = []  # In-memory cache
        self.last_checked: Dict[str, datetime] = {}  # Track who checked last
    
    async def post_message(self, from_agent: str, message: Dict, priority: str = "normal"):
        """Post a message to the blackboard."""
        entry = {
            "id": str(uuid.uuid4())[:8],
            "from_agent": from_agent,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": message,
            "priority": priority,  # "critical", "high", "normal", "low"
            "read_by": []
        }
        self.messages.append(entry)
        priority_icon = "🔴" if priority == "critical" else "🟡" if priority == "high" else "🔵"
        logger.info(f"{priority_icon} [BLACKBOARD: {self.topic_name}] {from_agent} → '{message.get('title', 'untitled')[:40]}' (ID: {entry['id']})")
        return entry["id"]
    
    async def get_new_messages(self, agent_id: str) -> List[Dict]:
        """Get messages posted since agent last checked."""
        last_check = self.last_checked.get(agent_id, datetime.min.replace(tzinfo=timezone.utc))
        new_messages = [
            msg for msg in self.messages
            if datetime.fromisoformat(msg["timestamp"]) > last_check
            and agent_id not in msg["read_by"]
        ]
        
        # Mark as read
        for msg in new_messages:
            msg["read_by"].append(agent_id)
        
        self.last_checked[agent_id] = datetime.now(timezone.utc)
        if new_messages:
            logger.info(f"📬 [{self.topic_name}] {agent_id} retrieved {len(new_messages)} new message(s)")
        return new_messages
    
    async def get_critical_messages(self, agent_id: str) -> List[Dict]:
        """Get only critical priority messages."""
        critical = [msg for msg in self.messages if msg["priority"] == "critical"]
        return [msg for msg in critical if agent_id not in msg["read_by"]]
    
    def to_dict(self) -> Dict:
        """Convert blackboard state to dict for persistence."""
        return {
            "topic_name": self.topic_name,
            "message_count": len(self.messages),
            "messages": self.messages[-20:]  # Keep last 20
        }

class BlackboardManager:
    """
    Manages all blackboards (central + group-based).
    Central blackboard: All agents read/write
    Group blackboards: Only dependent agents communicate
    Persists all communications to Cosmos DB for future audits.
    """
    def __init__(self, cosmos_manager=None, project_id: str = None):
        self.central_blackboard = Blackboard("team-central")
        self.group_blackboards: Dict[str, Blackboard] = {}  # group_id -> Blackboard
        self.agent_groups: Dict[str, Set[str]] = {}  # agent_id -> {group_ids}
        self.cosmos_manager = cosmos_manager  # For persisting communications
        self.project_id = project_id  # For organizing in Cosmos DB
        self._consumer_task: Optional[asyncio.Task] = None
    
    async def create_group_blackboard(self, group_id: str, agent_ids: Set[str]):
        """Create a blackboard for a specific group of dependent agents."""
        self.group_blackboards[group_id] = Blackboard(f"group-{group_id}")
        for agent_id in agent_ids:
            if agent_id not in self.agent_groups:
                self.agent_groups[agent_id] = set()
            self.agent_groups[agent_id].add(group_id)
        logger.info(f"📋 [GROUP BLACKBOARD] Created '{group_id}' for {len(agent_ids)} agents: {', '.join(agent_ids)}")
    
    async def broadcast_to_central(self, from_agent: str, message: Dict, priority: str = "normal"):
        """Post message to central blackboard (visible to all agents) and persist to Cosmos DB."""
        message_id = await self.central_blackboard.post_message(from_agent, message, priority)
        
        # Persist to Cosmos DB if available
        if self.cosmos_manager and self.project_id:
            try:
                message_data = {
                    "id": message_id,
                    "from_agent": from_agent,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "message": message,
                    "priority": priority
                }
                self.cosmos_manager.save_blackboard_message(self.project_id, "team-central", message_data)
            except Exception as e:
                logger.warning(f"⚠️  Could not persist blackboard message to Cosmos DB: {e}")
        
        return message_id
    
    async def post_to_group(self, group_id: str, from_agent: str, message: Dict, priority: str = "normal"):
        """Post message to specific group blackboard and persist to Cosmos DB."""
        if group_id not in self.group_blackboards:
            logger.warning(f"⚠️  Group blackboard {group_id} not found")
            return None
        
        message_id = await self.group_blackboards[group_id].post_message(from_agent, message, priority)
        
        # Persist to Cosmos DB if available
        if self.cosmos_manager and self.project_id:
            try:
                message_data = {
                    "id": message_id,
                    "from_agent": from_agent,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "message": message,
                    "priority": priority
                }
                self.cosmos_manager.save_blackboard_message(self.project_id, group_id, message_data)
            except Exception as e:
                logger.warning(f"⚠️  Could not persist group message to Cosmos DB: {e}")
        
        return message_id
    
    async def get_agent_messages(self, agent_id: str) -> Dict:
        """Get all messages for an agent (central + group blackboards)."""
        messages = {
            "central": await self.central_blackboard.get_new_messages(agent_id),
            "groups": {}
        }
        
        # Get messages from all group blackboards agent is in
        for group_id in self.agent_groups.get(agent_id, set()):
            messages["groups"][group_id] = await self.group_blackboards[group_id].get_new_messages(agent_id)
        
        return messages
    
    async def get_critical_messages(self, agent_id: str) -> List[Dict]:
        """Get critical messages from all blackboards."""
        critical = await self.central_blackboard.get_critical_messages(agent_id)
        
        for group_id in self.agent_groups.get(agent_id, set()):
            critical.extend(await self.group_blackboards[group_id].get_critical_messages(agent_id))
        
        return critical

    async def start_service_bus_sync(self):
        """Optionally ingest coordination queue events into central blackboard."""
        if not ENABLE_SERVICE_BUS_CONSUMER or not SERVICE_BUS_STR or self._consumer_task:
            return
        self._consumer_task = asyncio.create_task(self._consume_coordination_events())
        logger.info("📡 Service Bus consumer started for coordination event sync")

    async def stop_service_bus_sync(self):
        """Stop background Service Bus consumer task."""
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            self._consumer_task = None

    async def _consume_coordination_events(self):
        while True:
            try:
                async with ServiceBusClient.from_connection_string(SERVICE_BUS_STR) as sb:
                    receiver: ServiceBusReceiver = sb.get_queue_receiver(
                        queue_name=AGENT_EXECUTION_QUEUE,
                        max_wait_time=5,
                    )
                    async with receiver:
                        async for message in receiver:
                            payload = str(message)
                            await self.broadcast_to_central(
                                "service_bus_sync",
                                {
                                    "title": "Service Bus Coordination Event",
                                    "body": payload[:800],
                                    "message_type": "service_bus_sync",
                                },
                                priority="low",
                            )
                            await receiver.complete_message(message)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"⚠️  Service Bus consumer loop issue: {e}")
                await asyncio.sleep(2)

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
    
    async def resolve_agent_conflict(self, agent_id: str, reason: str, context: Dict, ledger: TaskLedger) -> Dict:
        """
        Director AI resolves conflicts and ambiguities escalated by agents.
        Provides autonomous guidance without blocking execution.
        ENHANCED: Better context, clearer decision format, actionable guidance.
        """
        # Gather comprehensive project context for decision-making
        project_summary = {
            "user_intent": ledger.data.get('user_intent', '')[:300],
            "tech_stack": ledger.data.get('technology_stack', {}),
            "functional_requirements": ledger.data.get('functional_requirements', [])[:5],
            "existing_decisions": ledger.data.get('operation_log', [])[-5:] if ledger.data.get('operation_log') else [],
        }
        
        resolution_prompt = f"""You are the Director AI for an autonomous multi-agent swarm system.
An agent is requesting guidance to continue work. Your response MUST enable autonomous execution.

[AGENT REQUEST]
Agent ID: {agent_id}
Reason: {reason}
Context: {json.dumps(context, indent=2)[:800]}

[PROJECT CONTEXT]
Intent: {project_summary['user_intent']}
Tech Stack: {json.dumps(project_summary['tech_stack'], indent=2)[:500]}
Requirements: {json.dumps(project_summary['functional_requirements'], indent=2)[:300]}
Recent Decisions: {json.dumps(project_summary['existing_decisions'], indent=2)[:400]}

[YOUR TASK]
1. Analyze the escalation reason and project context
2. Make a CLEAR, FINAL decision that unblocks the agent
3. Provide specific, actionable guidance (not questions)
4. Recommend implementation steps
5. Set escalate_to_user=true ONLY if decision requires creative human input

[CRITICAL CONSTRAINTS]
- Decision must be implementable by the agent IMMEDIATELY
- Guidance must be specific and technical, not vague
- Do NOT ask the agent for more information
- Do NOT defer to user unless absolutely necessary
- Reasoning must reference project context

[RESPONSE FORMAT - MUST BE VALID JSON]
{{
    "decision": "Specific, actionable decision statement",
    "reasoning": "Why this decision is correct given project context",
    "guidance": "Step-by-step implementation guidance",
    "next_steps": ["Step 1", "Step 2", "Step 3"],
    "priority": "high",
    "escalate_to_user": false,
    "confidence": 0.95
}}"""

        response = self.client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": "You are the autonomous Director AI making project decisions. Always provide actionable guidance. Never defer without strong justification."},
                {"role": "user", "content": resolution_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.6  # Lower temperature for more consistent decisions
        )
        
        resolution = json.loads(response.choices[0].message.content)
        
        # Enhanced logging with full context
        logger.info(
            f"🧠 Director AI Resolution\n"
            f"   Agent: {agent_id}\n"
            f"   Reason: {reason}\n"
            f"   Decision: {resolution.get('decision', 'N/A')}\n"
            f"   Escalate: {resolution.get('escalate_to_user', False)}\n"
            f"   Confidence: {resolution.get('confidence', 0.0)}"
        )
        
        return resolution

# ==========================================
# 6. SPECIALIZED AGENT CLASSES
# ==========================================
class Agent:
    """
    Iterative Agent class with persistent memory, blackboard integration, and error recovery.
    Supports pause/resume, handoffs, and dynamic collaboration via the swarm model.
    """
    
    def __init__(self, agent_id: str, role: AgentRole, project_context: Dict, comm_hub: AgentCommunicationHub, 
                 collaboration_bus: CollaborationBus, checkpoint_manager: CheckpointManager, 
                 blackboard_manager: BlackboardManager, cosmos_manager=None, dependencies: List[str] = None,
                 audit_logger: 'AuditLogger' = None, requirements_manager: 'RequirementsManager' = None):
        self.agent_id = agent_id
        self.role = role
        self.project_context = project_context
        self.comm_hub = comm_hub
        self.collaboration_bus = collaboration_bus
        self.checkpoint_manager = checkpoint_manager
        self.blackboard_manager = blackboard_manager
        self.cosmos_manager = cosmos_manager
        self.audit_logger = audit_logger  # NEW: For comprehensive logging
        self.requirements_manager = requirements_manager  # NEW: For requirements tracking
        self.dependencies = dependencies or []
        self.status = AgentStatus.CREATED
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.outputs = {}
        self.generated_code = {}  # filename -> code content
        self.change_logs: Dict[str, FileChangeLog] = {}  # filename -> change history
        self.message_history: List[Dict] = []  # Full conversation history
        self.iteration_count = 0
        self.pending_handoffs: List[Handoff] = []
        self.last_error = None  # Track last error for recovery
        self.work_completed = False  # Flag to track task completion
        self.agent_dir = None  # Directory for this agent's files (with UUID)
        self.client = AzureOpenAI(
            api_key=AZURE_OPENAI_KEY,
            api_version=AZURE_OPENAI_API_VERSION,
            azure_endpoint=AZURE_OPENAI_ENDPOINT
        )
        logger.info(f"✨ Agent spawned: {self.agent_id} ({role.value}) - COPILOT EDIT MODE")

    def _trace(self, event: str, details: Optional[Dict[str, Any]] = None):
        """Runtime trace output with configurable verbosity."""
        if AGENT_TRACE_MODE == "off":
            return
        details = details or {}
        if AGENT_TRACE_MODE == "summary":
            compact = ", ".join(f"{k}={v}" for k, v in details.items())
            logger.info(f"🧭 [TRACE] {self.agent_id} | {event} | {compact}")
        elif AGENT_TRACE_MODE == "code":
            if "code_excerpt" in details:
                logger.info(f"🧭 [TRACE] {self.agent_id} | {event}\n{details['code_excerpt'][:1000]}")
            else:
                logger.info(f"🧭 [TRACE] {self.agent_id} | {event} | {details}")
        else:
            logger.info(f"🧭 [TRACE-RAW] {self.agent_id} | {event} | {details}")

    def _log_ai_response(self, response: str):
        """Log AI response to audit logger for inspection."""
        if self.audit_logger:
            self.audit_logger.log_ai_response(
                agent_id=self.agent_id,
                iteration=self.iteration_count,
                role=self.role.value,
                response=response
            )

    def _add_requirement(self, requirement: str):
        """Add a requirement to the role's requirements file."""
        if self.requirements_manager:
            self.requirements_manager.add_requirement(self.role.value, requirement)
            if self.audit_logger:
                self.audit_logger.log_requirement_addition(
                    agent_id=self.agent_id,
                    role=self.role.value,
                    requirement=requirement
                )

    def _is_coding_role(self) -> bool:
        return self.role.value in CODING_PHASE_ROLES

    def _build_execution_contract(self, task_context: Dict) -> str:
        """Build mandatory execution contract from ledger + user instructions on blackboard."""
        functional_reqs = task_context.get("functional_requirements", []) or []
        user_intent = task_context.get("user_intent", "")
        relevant_instructions: List[str] = []

        for msg in self.blackboard_manager.central_blackboard.messages:
            content = msg.get("message", {})
            if not isinstance(content, dict):
                continue
            from_agent = msg.get("from_agent", "")
            target_roles = content.get("target_roles", [])
            targeted = not target_roles or self.role.value in target_roles
            if content.get("message_type") == "user_instruction" and targeted:
                body = content.get("body") or content.get("title")
                if body:
                    relevant_instructions.append(str(body))
            elif from_agent == "user":
                body = content.get("body") or content.get("title")
                if body:
                    relevant_instructions.append(str(body))

        role_expectations = self._derive_role_expectations(" ".join(relevant_instructions))
        lines = [
            "MANDATORY EXECUTION CONTRACT:",
            f"- Role: {self.role.value}",
            f"- User intent: {user_intent[:250]}",
        ]
        if functional_reqs:
            lines.append("- Functional requirements from ledger:")
            lines.extend([f"  - {str(r)[:220]}" for r in functional_reqs[:12]])
        if relevant_instructions:
            lines.append("- User instructions from blackboard:")
            lines.extend([f"  - {instr[:220]}" for instr in relevant_instructions[-8:]])
        if role_expectations:
            lines.append("- Non-negotiable deliverables for your role:")
            lines.extend([f"  - {e}" for e in role_expectations])
        lines.append("- You must not output [COMPLETED] until all applicable deliverables are implemented.")
        return "\n".join(lines)

    def _derive_role_expectations(self, instruction_blob: str) -> List[str]:
        instruction_blob = (instruction_blob or "").lower()
        expectations: List[str] = []
        if self.role == AgentRole.BACKEND_ENGINEER:
            expectations.extend([
                "Implement at least 3 backend artifacts (server + route/service modules).",
                "Include concrete user and document APIs/services.",
            ])
            if "user service" in instruction_blob:
                expectations.append("Implement explicit User Service module and wire into routes.")
            if "document service" in instruction_blob:
                expectations.append("Implement explicit Document Service module and wire into routes.")
        elif self.role == AgentRole.FRONTEND_ENGINEER:
            expectations.extend([
                "Implement at least 3 frontend artifacts (app shell + pages/components).",
                "Use React routing and include dashboard flow.",
            ])
            if "redux" in instruction_blob:
                expectations.append("Add Redux store setup and connect at least one slice/selector.")
        elif self.role == AgentRole.QA_ENGINEER:
            expectations.append("Provide concrete test files, not only RFC/comments.")
        elif self.role == AgentRole.ML_ENGINEER:
            expectations.append("Provide concrete ML integration code (pipeline or inference endpoint).")
        return expectations

    def _contains_any(self, text: str, patterns: List[str]) -> bool:
        t = text.lower()
        return any(p.lower() in t for p in patterns)

    def _check_completion_readiness(self, task_context: Dict) -> Tuple[bool, List[str]]:
        """SOFTENED: Role-aware completion gate that prevents SHALLOW outputs but allows pragmatic solutions."""
        missing: List[str] = []
        files = list(self.generated_code.keys())
        all_text = "\n".join(self.generated_code.values()).lower()
        instruction_blob = self._build_execution_contract(task_context).lower()

        # SOFTENED: Must have at least 1 file for coding roles (was stricter)
        if self._is_coding_role() and not files:
            missing.append("Coding role must generate at least one file.")
            return False, missing

        if self.role == AgentRole.BACKEND_ENGINEER:
            # SOFTENED: At least 1 file (was 3)
            if len(files) < 1:
                missing.append("Backend requires at least 1 core file.")
            # SOFTENED: Check for ANY auth/doc handling (not both required)
            has_content = self._contains_any(
                all_text + " " + " ".join(files),
                ["auth", "login", "register", "document", "upload", "download", "api", "route", "service"]
            )
            if not has_content:
                missing.append("Backend should include auth or document handling.")
        
        elif self.role == AgentRole.FRONTEND_ENGINEER:
            # SOFTENED: At least 1 component (was 3)
            if len(files) < 1:
                missing.append("Frontend requires at least 1 component/page.")
            # SOFTENED: Check for UI content (not specific dashboard)
            has_ui = self._contains_any(
                all_text + " " + " ".join(files),
                ["login", "auth", "button", "form", "component", "react", "tsx", "jsx"]
            )
            if not has_ui:
                missing.append("Frontend should include UI components.")
        
        elif self.role == AgentRole.QA_ENGINEER:
            # SOFTENED: At least 1 test file
            if not any(fn.startswith("test") or "spec" in fn.lower() or "test" in fn.lower() for fn in files):
                missing.append("QA role should generate at least one test file.")
        
        elif self.role == AgentRole.ML_ENGINEER:
            # SOFTENED: Any ML artifact (not strict)
            if not self._contains_any(all_text + " " + " ".join(files), ["model", "pipeline", "inference", "predict", "train"]):
                missing.append("ML role should include model or pipeline code.")

        return len(missing) == 0, missing

    async def execute_iteratively(self, task_context: Dict) -> Dict:
        """
        Execute the agent in an iterative loop with error recovery and persistent state.
        Agents loop until they explicitly output [COMPLETED].
        """
        self.status = AgentStatus.IN_PROGRESS
        max_iterations = MAX_AGENT_ITERATIONS
        
        while self.status == AgentStatus.IN_PROGRESS and self.iteration_count < max_iterations:
            self.iteration_count += 1
            logger.info(f"🔄 Agent {self.agent_id} iteration {self.iteration_count}/{max_iterations}")
            
            try:
                # Step 0a: Check for completed dependencies - AUTO-WAKE if dependencies finished
                dependencies_ready = await self._check_and_report_dependencies()
                if dependencies_ready and self.status == AgentStatus.PAUSED:
                    logger.info(f"🔄 ⚡ {self.agent_id} dependencies completed - RESUMING WORK")
                    self.status = AgentStatus.IN_PROGRESS
                    # Add dependency completion notice to context
                    self.message_history.append({
                        "role": "system",
                        "content": "Your dependencies have completed. You can now proceed with your work."
                    })
                
                # Step 0b: Check blackboards for critical messages
                critical_msgs = await self.blackboard_manager.get_critical_messages(self.agent_id)
                if critical_msgs:
                    logger.info(f"🔔 {self.agent_id} received {len(critical_msgs)} critical message(s)")
                    for msg in critical_msgs:
                        self.message_history.append({
                            "role": "system",
                            "content": f"CRITICAL UPDATE FROM TEAM: {msg['message']}"
                        })
                
                # Step 1: Check for pending handoffs to process
                pending = await self.collaboration_bus.get_pending_handoffs(self.agent_id)
                if pending:
                    logger.info(f"📨 {self.agent_id} has {len(pending)} pending handoff(s)")
                    for handoff in pending:
                        await self._process_handoff(handoff)
                    continue  # Re-evaluate after handling handoff
                
                # Step 2: Generate next step with AI
                execution_contract = self._build_execution_contract(task_context)
                if not self.message_history or self.message_history[-1].get("content", "") != execution_contract:
                    self.message_history.append({
                        "role": "system",
                        "content": execution_contract
                    })
                response_text = await self._get_ai_response(task_context)
                trace_payload: Dict[str, Any] = {"iteration": self.iteration_count, "chars": len(response_text)}
                if AGENT_TRACE_MODE in {"code", "raw"}:
                    trace_payload["code_excerpt"] = response_text[:2000]
                self._trace("ai_response", trace_payload)
                
                # Step 3: Check for explicit completion directive
                if "[COMPLETED]" in response_text or "TASK_COMPLETED:" in response_text:
                    if REQUIRE_OUTPUT_FOR_COMPLETION and self._is_coding_role() and len(self.generated_code) == 0:
                        self.message_history.append({
                            "role": "system",
                            "content": (
                                "Completion rejected: coding role cannot complete with zero generated files. "
                                "Generate at least one concrete artifact before [COMPLETED]."
                            ),
                        })
                        self._trace(
                            "completion_rejected",
                            {"reason": "no_output", "role": self.role.value, "files": len(self.generated_code)},
                        )
                        continue
                    ready, missing = self._check_completion_readiness(task_context)
                    if not ready:
                        self.message_history.append({
                            "role": "system",
                            "content": (
                                "Completion rejected. Missing required deliverables:\n- " +
                                "\n- ".join(missing) +
                                "\nContinue implementation and only then output [COMPLETED]."
                            ),
                        })
                        self._trace(
                            "completion_rejected",
                            {"reason": "deliverables_missing", "missing": len(missing)},
                        )
                        continue
                    logger.info(f"✅ Agent {self.agent_id} explicitly marked task completed")
                    self._trace("directive_detected", {"directive": "COMPLETED"})
                    self.work_completed = True
                    self.status = AgentStatus.COMPLETED
                    
                    # NEW: Save final code artifacts to Cosmos DB
                    if self.cosmos_manager:
                        for filename, content in self.generated_code.items():
                            self.cosmos_manager.save_final_code_artifact(
                                project_id=task_context.get("project_id", "unknown"),
                                agent_id=self.agent_id,
                                role=self.role.value,
                                filename=filename,
                                content=content,
                                iteration=self.iteration_count
                            )
                    
                    # Post completion to blackboard so dependent agents can wake up
                    try:
                        completion_msg = {
                            "title": f"[COMPLETED] {self.role.value} task",
                            "body": f"Agent {self.agent_id} ({self.role.value}) completed after {self.iteration_count} iterations with {len(self.generated_code)} files.",
                            "from_agent": self.agent_id,
                            "role": self.role.value,
                            "files_generated": len(self.generated_code),
                            "agent_id": self.agent_id,
                            "status": "COMPLETED"
                        }
                        await self.blackboard_manager.broadcast_to_central(self.agent_id, completion_msg, priority="high")
                        logger.info(f"📢 Posted completion message to blackboard for {self.role.value}")
                    except Exception as e:
                        logger.warning(f"Could not post completion to blackboard: {e}")
                    
                    break
                
                # Step 4: Parse response for control flow
                if "PAUSE_FOR_USER:" in response_text:
                    self._trace("directive_detected", {"directive": "PAUSE_FOR_USER"})
                    pause_reason = response_text.split("PAUSE_FOR_USER:")[-1].split("\n")[0].strip()
                    logger.info(f"🧠 Agent {self.agent_id} escalating to Director AI: {pause_reason}")
                    
                    # Escalate to Director AI instead of pausing for user
                    await self.blackboard_manager.broadcast_to_central(
                        from_agent=self.agent_id,
                        message={
                            "title": f"DIRECTOR_AI_RESOLUTION_NEEDED",
                            "type": "resolution_request",
                            "agent_id": self.agent_id,
                            "reason": pause_reason,
                            "iteration": self.iteration_count,
                            "context": task_context
                        },
                        priority="high"
                    )
                    
                    self.status = AgentStatus.WAITING_FOR_RESPONSE
                    await self._save_checkpoint(f"Waiting for Director AI resolution: {pause_reason}")
                    break
                
                elif "HANDOFF_TO:" in response_text:
                    self._trace("directive_detected", {"directive": "HANDOFF_TO"})
                    target_agent = await self._extract_handoff_target(response_text)
                    if target_agent:
                        logger.info(f"🤝 Agent {self.agent_id} requesting handoff to {target_agent}")
                        handoff = Handoff(
                            from_agent=self.agent_id,
                            to_agent=target_agent,
                            context={"iteration": self.iteration_count, "message": response_text}
                        )
                        await self.collaboration_bus.post_handoff(handoff)
                        self.status = AgentStatus.WAITING_FOR_RESPONSE
                        break
                    
                elif "REQUEST_COMMENT:" in response_text or "[RFC]" in response_text:
                    # Block RFC posting until iteration 4+ to force code generation first
                    if self.iteration_count <= 3:
                        self.message_history.append({
                            "role": "system",
                            "content": (
                                "RFC blocked: Cannot post [RFC] during iterations 1-3. "
                                "Focus on generating actual code first. After iteration 3, RFCs are allowed."
                            ),
                        })
                        self._trace("rfc_blocked", {"reason": "too_early", "iteration": self.iteration_count})
                        continue  # Skip RFC and go to next iteration to generate code
                    
                    self._trace("directive_detected", {"directive": "RFC"})
                    rfc_title = await self._extract_rfc_title(response_text)
                    rfc = RequestForComment(
                        author=self.agent_id,
                        title=rfc_title,
                        description=response_text,
                        tags=[self.role.value]
                    )
                    await self.collaboration_bus.post_rfc(rfc)
                    logger.info(f"📝 Agent {self.agent_id} posted RFC: {rfc_title}")
                    if RFC_BLOCKING_MODE:
                        self.status = AgentStatus.WAITING_FOR_RESPONSE
                        break
                    self.message_history.append({
                        "role": "system",
                        "content": "RFC posted. Continue implementing deliverables unless explicitly blocked."
                    })
                    continue
                
                # Step 5: Normal execution - parse code and validate (with error recovery)
                # FIRST: Check for placeholder code
                has_placeholder, placeholder_msg = PlaceholderDetector.check_for_placeholders(response_text)
                if has_placeholder:
                    error_msg = PlaceholderDetector.get_placeholder_error_message()
                    self.message_history.append({
                        "role": "system",
                        "content": error_msg
                    })
                    logger.warning(f"⚠️  {placeholder_msg} in {self.agent_id}")
                    continue  # Skip to next iteration and ask for real code
                
                try:
                    parse_info = self._parse_and_save_code(response_text)
                    self.last_error = None  # Clear error on success
                    self._trace("parse_result", parse_info)
                    
                    # NEW: Check for requirement tracking in generated code
                    requirements_check = self._check_requirements_in_code(response_text)
                    if requirements_check["missing_requirements"]:
                        logger.warning(f"⚠️  {self.agent_id} has undocumented dependencies: {requirements_check['missing_requirements']}")
                        missing_list = "\\n".join([f"  - {req}" for req in requirements_check["missing_requirements"]])
                        requirement_feedback = f"""REQUIREMENT TRACKING ISSUE:
The following packages are used in code but NOT logged to requirements:
{missing_list}

REQUIRED ACTION:
1. For each missing package, add: self._add_requirement('package-name@version')
2. Examples:
   - self._add_requirement('express@^4.18.2')
   - self._add_requirement('react@^18.2.0')
   - self._add_requirement('pytest>=7.2.0')
3. Use semantic versioning (^X.Y.Z for compatible versions, ~X.Y.Z for patches)
4. Regenerate the code in the next iteration with proper requirement logging
5. Cannot complete until ALL external packages are documented."""
                        self.message_history.append({
                            "role": "system",
                            "content": requirement_feedback
                        })
                        logger.info(f"🔴 {self.agent_id} iteration {self.iteration_count}: Blocking on missing requirements")
                        continue  # Skip to next iteration until requirements are logged
                    
                except Exception as e:
                    logger.warning(f"⚠️  Error parsing code for {self.agent_id}: {e}")
                    self.last_error = str(e)
                    # Provide specific feedback to agent about the error
                    error_feedback = f"""ERROR in code processing:
Type: {type(e).__name__}
Details: {str(e)}

CORRECTIVE ACTION REQUIRED:
1. Review the code block formatting - ensure each file is wrapped in triple backticks
2. Format: ```filename.ext
3. Include the complete, valid code
4. End with closing backticks ```
5. Retry the code generation with proper formatting"""
                    self.message_history.append({
                        "role": "system",
                        "content": error_feedback
                    })
                    continue  # Skip to next iteration
                
                self._extract_metadata_and_communicate(response_text)
                
                # PERSIST MESSAGE HISTORY after successful code generation
                project_id = self.project_context.get("project_id", "unknown")
                if hasattr(self, 'cosmos_manager') and self.cosmos_manager:
                    await self.cosmos_manager.save_message_history(
                        project_id,
                        self.agent_id,
                        self.iteration_count,
                        self.message_history
                    )
                    
                    # PERSIST FILE CHANGE LOGS for audit trail and undo capability
                    for filename, changelog in self.change_logs.items():
                        await self.cosmos_manager.save_file_change_log(
                            project_id,
                            self.agent_id,
                            filename,
                            changelog
                        )
                
                # Step 6: Run validation
                validation_result = await self._run_validation()
                self._trace(
                    "validation",
                    {
                        "success": validation_result.get("success"),
                        "issues": len(validation_result.get("issues", [])),
                    },
                )
                if not validation_result["success"]:
                    # Provide validation feedback to agent
                    issues_text = "\n".join([
                        f"  - {issue['file']}: {issue['message']}"
                        for issue in validation_result.get('issues', [])
                    ])
                    validation_feedback = f"""VALIDATION ISSUES FOUND:
{issues_text}

REQUIRED ACTIONS:
1. Review each issue carefully
2. Fix syntax errors and import problems
3. Ensure all code follows Python best practices
4. Regenerate the code in the next iteration"""
                    self.message_history.append({
                        "role": "system",
                        "content": validation_feedback
                    })
                    logger.info(f"ℹ️  Validation note: {validation_result.get('feedback', 'continue')}")
                else:
                    logger.info(f"✓ Validation passed for {self.agent_id}")

                
                # Step 7: Continue to next iteration for refinement
                logger.info(f"→ Agent {self.agent_id} continuing to refine work...")
                    
            except Exception as e:
                logger.error(f"❌ Agent {self.agent_id} error in iteration {self.iteration_count}: {str(e)}")
                self.last_error = str(e)
                # Provide error context to agent for recovery
                error_context = f"""ITERATION ERROR - Agent recovery required:
Error Type: {type(e).__name__}
Message: {str(e)}

RECOVERY INSTRUCTIONS:
1. The previous operation failed unexpectedly
2. Review your last response for issues
3. Try a different approach in the next iteration
4. If the issue persists, simplify your approach

You have {max_iterations - self.iteration_count} iterations remaining."""
                self.message_history.append({
                    "role": "system",
                    "content": error_context
                })
                # Continue to next iteration instead of failing immediately
                if self.iteration_count < max_iterations:
                    logger.info(f"→ Agent {self.agent_id} will attempt recovery in next iteration...")
                    continue
                else:
                    self.status = AgentStatus.FAILED
                    break
        
        if self.iteration_count >= max_iterations and self.status == AgentStatus.IN_PROGRESS:
            logger.warning(f"⚠️  Agent {self.agent_id} reached max iterations ({max_iterations})")
            ready, missing = self._check_completion_readiness(task_context)
            if ready:
                logger.info(f"   NOTE: Max iterations reached with deliverables satisfied. Marking completed.")
                self.status = AgentStatus.COMPLETED
                self.work_completed = True
            else:
                logger.warning(f"   Incomplete deliverables at max iterations: {missing}")
                self.status = AgentStatus.FAILED
                self.work_completed = False
        
        # Post completion to team if work done
        if self.work_completed:
            await self.blackboard_manager.broadcast_to_central(
                self.agent_id,
                {
                    "title": f"{self.role.value} work completed",
                    "files": list(self.generated_code.keys()),
                    "iterations": self.iteration_count
                },
                priority="high"
            )
        
        return {
            "status": self.status.value,
            "agent_id": self.agent_id,
            "files_generated": list(self.generated_code.keys()),
            "role": self.role.value,
            "iterations": self.iteration_count,
            "work_completed": self.work_completed,
            "last_error": self.last_error
        }
    
    async def _get_ai_response(self, task_context: Dict) -> str:
        """Get AI response with full context from message history and project."""
        profile = AgentRegistry.get_agent_profile(self.role)
        
        # Build context from previous iterations
        history_context = ""
        if self.message_history:
            history_context = "\n\nPREVIOUS ITERATIONS:\n"
            for i, msg in enumerate(self.message_history[-5:], 1):  # Last 5 iterations
                history_context += f"  {i}. {msg.get('content', '')[:200]}...\n"
        
        role_display = self.role.value.replace('_', ' ').title()
        
        # Determine MODE based on iteration number
        mode_guidance = "MODE 1: FULL FILE" if self.iteration_count == 1 else "MODE 2: SEARCH/REPLACE (atomic edits - MUCH FASTER)"
        
        # For first 3 iterations, COMPLETELY OMIT collaboration mandates to avoid confusion
        # Only include them AFTER code generation is done (iteration 4+)
        collaboration_section = ""
        if self.iteration_count <= 3:
            collaboration_section = f"""
⛔ CRITICAL - ITERATIONS 1-3 ARE FOR CODE GENERATION ONLY ⛔
- You must NOT post [RFC], REQUEST_COMMENT, or ask for feedback
- You must NOT delegate (no HANDOFF_TO)
- You must NOT pause for user input
- Your ONLY job: Generate actual, complete, production-ready code
- After iteration 3, collaboration becomes available
"""
        else:
            collaboration_mandate = self._get_collaboration_mandate()
            collaboration_section = f"""
COLLABORATION MANDATE (After Code Generation):
{collaboration_mandate}"""
        
        # BUILD REQUIREMENTS TRACKING MANDATE
        requirements_mandate = f"""🚀 REQUIREMENT TRACKING - MANDATORY AT EVERY ITERATION 🚀
YOU MUST LOG EVERY EXTERNAL PACKAGE YOU USE IN YOUR RESPONSE TEXT ONLY:

⚠️ CRITICAL: Requirements go ONLY in your response text, NEVER embedded in generated code.

1. WHEN ADDING IMPORTS TO CODE:
   - The code you generate must be clean and production-ready
   - List the requirement in your RESPONSE TEXT as:
     "Requirement: package-name@version"
   - Examples in response text:
     * "Requirement: express@^4.18.2 (for HTTP server)"
     * "Requirement: react@^18.2.0 (for UI components)"
     * "Requirement: pytest>=7.2.0 (for testing)"

2. FOR ALL DEPENDENCIES IN CODE:
   - Every require() in JS → mention in response text
   - Every import in Python → mention in response text
   - Every npm/pip package used → mention in response text
   - NEVER write self._add_requirement() calls inside code files
   - NEVER put requirement tracking code in generated files

3. WHAT NOT TO DO (❌ WRONG):
   ❌ self._add_requirement('express@^4.18.2') inside server.js
   ❌ Any requirement tracking code in generated files
   ❌ Generated code that will crash when executed

4. WHAT TO DO (✅ RIGHT):
   ✅ Generate clean, valid code (no special logging calls)
   ✅ List requirements in your response text: "Requirement: package@version"
   ✅ System parses requirements from response text automatically

5. BEFORE [COMPLETED]:
   - Verify all imports are mentioned in response text
   - Ensure generated code is valid and production-ready
   - Check all requirements listed in RESPONSE TEXT, not code
"""
        
        # BUILD DOCUMENTATION MANDATE  
        documentation_mandate = f"""📝 CODE DOCUMENTATION - MANDATORY AT EVERY ITERATION 📝
YOU MUST DOCUMENT YOUR CODE AND GENERATE README:

1. FILE HEADERS (every code file):
   - Purpose, dependencies, author
   - Example: '''Purpose: User authentication. Deps: PyJWT, bcryptjs'''

2. FUNCTION DOCSTRINGS (every function):
   - What it does, args, return value
   - Include type hints
   - Example: '''Authenticate user. Args: email(str), password(str). Returns: JWT token'''

3. IMPORT COMMENTS:
   - Why each package is needed
   - Example: # For JWT token handling

4. CONFIG DOCUMENTATION:
   - Required environment variables
   - Example: # Requires: DATABASE_URL, JWT_SECRET

5. README.md FILE (MANDATORY):
   - Create README.md in your code directory explaining:
     * What the code does (1-2 sentences)
     * Prerequisites and dependencies
     * How to install/setup (step by step)
     * How to run the code
     * Configuration required (env vars, config files)
     * Example: npm install && npm start

Missing documentation or README = REJECTION
"""
        
        system_prompt = f"""You are a {role_display} in Agentic Nexus (Copilot Mode).

{profile["system_prompt_template"].format(context=json.dumps(task_context, indent=2))}

🚨 CRITICAL - ITERATION {self.iteration_count} MODE: {mode_guidance}
{collaboration_section}

{requirements_mandate}

{documentation_mandate}

⛔ PLACEHOLDER REJECTION POLICY - MANDATORY ⛔
You will NOT output:
- "..." or ellipsis in code blocks (IMMEDIATE REJECTION)
- "<complete ...>" or "<implementation ...>"
- "TODO:" or "FIXME:" comments
- "[Your code here]" or "[implementation here]"
- "pass" statements with TODO
- Incomplete functions with only docstrings

IF YOU OUTPUT ANY PLACEHOLDER: System rejects it, forces retry.
Every line must be COMPLETE and FUNCTIONAL.

ITERATIVE EXECUTION MODE - How to exit:
When you have finished ALL assigned work:
1. Verify all deliverables are generated (code + README.md)
2. Log all requirements in your RESPONSE TEXT using format: "Requirement: package@version"
3. Document all code with headers and docstrings
4. Ensure generated code is valid, production-ready (no requirement tracking code)
5. Check team feedback on blackboard
6. Output [COMPLETED] on its own line to signal task completion

ITERATION {self.iteration_count} PRIORITY:
{"🔴 GENERATE CODE FIRST - DO NOT POST [RFC] YET" if self.iteration_count <= 3 else "You can post [RFC] for team feedback after generating code"}

{history_context}

CODE GENERATION RULES FOR ITERATION {self.iteration_count}:
- Use {"FULL FILE format (complete files)" if self.iteration_count == 1 else "SEARCH/REPLACE format (atomic edits only)"}
- All code MUST be ACTUAL, PRODUCTION-READY (zero placeholders)
- Complete, functional, ready to run
- Proper error handling, logging, documentation
- Follow best practices for your role
- Copilot-like atomic edits reduce errors and token waste
- Each SEARCH/REPLACE block = ONE surgical edit
- SEARCH text MUST EXACTLY match existing code (whitespace matters)
- LOG EACH REQUIREMENT via self._add_requirement()
- INCLUDE FILE HEADERS with dependencies documented
- INCLUDE DOCSTRINGS for all functions with args/returns
- COMMENT IMPORTS explaining why each package is needed

⚠️ WARNING: Missing requirements or docs = IMMEDIATE REJECTION AND RETRY
You will not advance until code is complete, documented, AND all requirements are logged.

{"⛔ CRITICAL: You MUST include code blocks (```filename```) in this iteration. Failing to do so will restart the entire iteration." if self.iteration_count <= 3 else ""}"""
        
        response = self.client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(task_context, indent=2)}
            ] + self.message_history,
            temperature=0.7
        )
        
        response_text = response.choices[0].message.content
        
        # Log AI response for audit trail [NEW]
        self._log_ai_response(response_text)
        
        # Store in message history for next iteration
        self.message_history.append({
            "role": "assistant",
            "content": response_text[:500]  # Store summary
        })
        
        return response_text
    
    def _get_collaboration_mandate(self) -> str:
        """Return role-specific collaboration mandates that force agents to collaborate."""
        mandates = {
            AgentRole.BACKEND_ENGINEER: """REQUIRED COLLABORATION:
  - MUST post [RFC] requesting confirmation from database_architect on schema before finalizing models
  - MUST post [RFC] requesting endpoint validation from frontend_engineer before API finalization
  - MUST include authentication with [RFC] to security_engineer for auth approach review""",
            
            AgentRole.FRONTEND_ENGINEER: """REQUIRED COLLABORATION:
  - MUST post [RFC] requesting API endpoint confirmation from backend_engineer
  - MUST post [RFC] requesting auth flow validation from security_engineer
  - MUST request ML analysis features list from ml_engineer before building UI components""",
            
            AgentRole.DATABASE_ARCHITECT: """REQUIRED COLLABORATION:
  - MUST post [RFC] on final schema for backend_engineer review before finalization
  - MUST coordinate with security_engineer on data encryption/access patterns""",
            
            AgentRole.QA_ENGINEER: """REQUIRED COLLABORATION:
  - MUST wait for backend_engineer and frontend_engineer code before creating tests
  - MUST post [RFC] requesting test strategy approval from solution_architect""",
            
            AgentRole.SECURITY_ENGINEER: """REQUIRED COLLABORATION:
  - MUST post [RFC] on authentication/encryption approach for backend_engineer review
  - MUST coordinate with devops_engineer on secrets management in deployment""",
            
            AgentRole.ML_ENGINEER: """REQUIRED COLLABORATION:
  - MUST post [RFC] on ML pipeline integration points for backend_engineer review
  - MUST post [RFC] on feature requirements to guide frontend_engineer UI design""",
            
            AgentRole.DEVOPS_ENGINEER: """REQUIRED COLLABORATION:
  - MUST post [RFC] on deployment pipeline for security_engineer secrets review
  - MUST coordinate infrastructure with backend_engineer on runtime requirements""",
            
            AgentRole.SOLUTION_ARCHITECT: """REQUIRED COLLABORATION:
  - MUST coordinate with all agents to ensure aligned architecture
  - MUST post [RFC] on system design decisions for team review before implementation""",
            
            AgentRole.API_DESIGNER: """REQUIRED COLLABORATION:
  - MUST post [RFC] on API specification for backend_engineer implementation review
  - MUST post [RFC] requesting SDKs review from backend_engineer""",
        }
        
        mandate = mandates.get(self.role, "Collaborate with team on critical decisions using [RFC].")
        return mandate
    
    async def _process_handoff(self, handoff: Handoff):
        """Process an incoming handoff by incorporating its results."""
        logger.info(f"🔄 Processing handoff from {handoff.from_agent}")
        if handoff.result:
            self.message_history.append({
                "role": "system",
                "content": f"Handoff result from {handoff.from_agent}: {json.dumps(handoff.result)[:200]}"
            })
        await self.collaboration_bus.complete_handoff(handoff.id, {"processed": True})
    
    async def _extract_handoff_target(self, response_text: str) -> Optional[str]:
        """Extract the target agent from HANDOFF_TO directive."""
        match = re.search(r"HANDOFF_TO:\s*(\w+(?:_\w+)?)", response_text)
        if match:
            return match.group(1)
        return None
    
    async def _extract_rfc_title(self, response_text: str) -> str:
        """Extract RFC title from REQUEST_COMMENT directive."""
        match = re.search(r"REQUEST_COMMENT:\s*([^\n]+)", response_text)
        if match:
            return match.group(1).strip()
        return f"RFC from {self.agent_id}"
    
    async def _check_and_report_dependencies(self) -> bool:
        """
        Check if all dependencies for this agent have completed.
        Returns True if all dependencies are done, False otherwise.
        Monitors the blackboard for dependency completion posts.
        """
        if not self.dependencies:
            return True  # No dependencies = ready to go
        
        completed_deps = set()
        
        # Check 1: Local blackboard for completion messages from dependencies
        all_central_msgs = self.blackboard_manager.central_blackboard.messages
        for msg in all_central_msgs:
            from_agent = msg.get("from_agent", "").lower()
            msg_content = str(msg.get("message", {})).lower()
            msg_title = msg.get("message", {}).get("title", "").lower()
            
            for dep_role in self.dependencies:
                dep_role_lower = dep_role.lower()
                
                # Check if message is from this dependency role
                is_from_dep = (
                    dep_role_lower in from_agent or 
                    dep_role_lower in msg_content or
                    dep_role_lower in msg_title
                )
                
                # Check if message indicates completion
                is_completion = (
                    "[completed]" in msg_title or
                    "completed" in msg_title or
                    msg.get("message", {}).get("status") == "COMPLETED"
                )
                
                if is_from_dep and is_completion:
                    completed_deps.add(dep_role)
                    if dep_role not in getattr(self, '_logged_deps', set()):
                        logger.info(f"✅ {self.agent_id} detected dependency '{dep_role}' completed from blackboard")
                        if not hasattr(self, '_logged_deps'):
                            self._logged_deps = set()
                        self._logged_deps.add(dep_role)
                    break
        
        # Check if all dependencies are satisfied
        deps_satisfied = len(completed_deps) == len(self.dependencies)
        
        if deps_satisfied and self.status == AgentStatus.WAITING_FOR_RESPONSE:
            logger.info(f"🚀 {self.agent_id} all dependencies satisfied - AUTO-RESUMING")
            self.status = AgentStatus.IN_PROGRESS
            return True
        
        if deps_satisfied and self.status == AgentStatus.PAUSED:
            logger.info(f"🚀 {self.agent_id} all dependencies satisfied - RESUMING FROM PAUSE")
            self.status = AgentStatus.IN_PROGRESS
            return True
        
        return deps_satisfied
    
    async def _save_checkpoint(self, reason: str):
        """Save current agent state to Cosmos DB for later resumption."""
        checkpoint_state = {
            "agent_id": self.agent_id,
            "role": self.role.value,
            "status": self.status.value,
            "iteration": self.iteration_count,
            "message_history": self.message_history,
            "generated_code": self.generated_code,
            "pause_reason": reason,
            "project_context": self.project_context
        }
        await self.checkpoint_manager.save_checkpoint(self.agent_id, checkpoint_state)
    
    async def _run_validation(self) -> Dict:
        """Run validation tests on generated code - syntax, imports, basic linting."""
        issues = []
        success = True
        
        # Validate Python files for syntax errors
        for filename, code in self.generated_code.items():
            if filename.endswith('.py'):
                try:
                    ast.parse(code)
                except SyntaxError as e:
                    issues.append({
                        "file": filename,
                        "type": "syntax_error",
                        "message": f"Line {e.lineno}: {e.msg}"
                    })
                    success = False
                    logger.warning(f"⚠️  Syntax error in {filename}: Line {e.lineno}: {e.msg}")
                
                # Check for common import issues
                try:
                    tree = ast.parse(code)
                    imports = []
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                imports.append(alias.name.split('.')[0])
                        elif isinstance(node, ast.ImportFrom):
                            if node.module:
                                imports.append(node.module.split('.')[0])
                    
                    # Check standard library and common packages (basic validation)
                    problematic = []
                    for imp in set(imports):
                        if imp not in ('os', 'sys', 'json', 're', 'asyncio', 'logging', 
                                      'datetime', 'uuid', 'pathlib', 'typing', 'enum',
                                      'fastapi', 'pydantic', 'sqlalchemy', 'pytest',
                                      'numpy', 'pandas', 'sklearn', 'react', 'typescript',
                                      'docker', 'kubernetes', '__future__'):
                            pass  # Don't fail on unknown imports, just log
                except Exception as e:
                    logger.warning(f"⚠️  Could not validate imports in {filename}: {e}")

            # Validate JS/TS relative imports for missing generated modules
            if filename.endswith(('.js', '.jsx', '.ts', '.tsx')):
                try:
                    relative_imports = re.findall(r"from\s+['\"](\./[^'\"]+)['\"]", code)
                    relative_imports += re.findall(r"require\(\s*['\"](\./[^'\"]+)['\"]\s*\)", code)
                    for rel in relative_imports:
                        base = rel[2:]  # strip "./"
                        candidates = [
                            base,
                            f"{base}.js",
                            f"{base}.jsx",
                            f"{base}.ts",
                            f"{base}.tsx",
                            f"{base}/index.js",
                            f"{base}/index.ts",
                            f"{base}/index.tsx",
                        ]
                        if not any(c in self.generated_code for c in candidates):
                            issues.append({
                                "file": filename,
                                "type": "missing_import_target",
                                "message": f"Relative import '{rel}' has no generated target file"
                            })
                            success = False
                except Exception as e:
                    logger.warning(f"⚠️  Could not validate JS/TS imports in {filename}: {e}")
        
        if issues:
            logger.warning(f"⚠️  Validation found {len(issues)} issue(s)")
        
        return {
            "success": success,
            "issues": issues,
            "feedback": "Code validation complete" if success else f"{len(issues)} issue(s) found"
        }

    def _check_requirements_in_code(self, response_text: str) -> Dict[str, Any]:
        """Check if code has undocumented external dependencies."""
        import_patterns = {
            "python": [
                r"^\s*import\s+(\w+)",
                r"^\s*from\s+(\w+)",
            ],
            "javascript": [
                r"const\s+\w+\s*=\s*require\(['\"]([^'\"]+)['\"]",
                r"import\s+.*from\s+['\"]([^'\"]+)['\"]",
            ],
            "nodejs": [
                r"require\(['\"]([^'\"]+)['\"]",
            ]
        }
        
        # Extract all imports from generated code
        found_imports = set()
        for filename, code in self.generated_code.items():
            if filename.endswith('.py'):
                patterns = import_patterns["python"]
            elif filename.endswith(('.js', '.jsx', '.ts', '.tsx')):
                patterns = import_patterns["javascript"] + import_patterns["nodejs"]
            else:
                continue
                
            for pattern in patterns:
                matches = re.findall(pattern, code, re.MULTILINE)
                for match in matches:
                    # Filter out relative imports
                    if not match.startswith('.') and not match.startswith('/'):
                        # Get first part (e.g., 'express' from 'express/router')
                        base_import = match.split('/')[0]
                        found_imports.add(base_import)
        
        # Check which imports are NOT in the response text (not self._add_requirement calls)
        if not response_text:
            return {"missing_requirements": [], "found_imports": list(found_imports)}
        
        # Look for requirement logging in response
        requirement_pattern = r"self\._add_requirement\(['\"]([^'\"]+)['\"]\)"
        logged_requirements = set(re.findall(requirement_pattern, response_text))
        
        # Extract just the package names from logged requirements (remove @version)
        logged_packages = set()
        for req in logged_requirements:
            pkg_name = req.split('@')[0].split('[')[0]  # Handle 'pkg@version' and 'pkg[extra]'
            logged_packages.add(pkg_name)
        
        # Standard library modules that don't need logging
        stdlib_modules = {
            'os', 'sys', 'json', 're', 'asyncio', 'logging', 'datetime', 'uuid',
            'pathlib', 'typing', 'enum', 'abc', 'collections', 'itertools', 'functools',
            'math', 'random', 'time', 'datetime', 'io', 'pickle', 'csv', 'configparser',
            'socket', 'threading', 'multiprocessing', 'queue', 'subprocess', 'unittest',
            'pytest', '__future__'
        }
        
        # Find undocumented imports
        missing_requirements = []
        for imp in found_imports:
            if imp not in logged_packages and imp not in stdlib_modules:
                missing_requirements.append(imp)
        
        return {
            "missing_requirements": sorted(missing_requirements),
            "found_imports": sorted(found_imports),
            "logged_packages": sorted(logged_packages)
        }

    def _check_code_documentation(self, response_text: str) -> Dict[str, Any]:
        """Check if code includes proper documentation (file headers, docstrings)."""
        issues = []
        
        # Extract code blocks from response
        code_blocks = re.findall(r"```([^`]+?)```", response_text, re.DOTALL)
        
        for block in code_blocks:
            lines = block.split('\n')
            if not lines:
                continue
                
            # Get filename (first line should be filename)
            filename = lines[0].strip() if lines else "unknown"
            code = '\n'.join(lines[1:]) if len(lines) > 1 else block
            
            # Check for Python file headers
            if filename.endswith('.py'):
                has_file_header = (
                    '"""' in code or "'''" in code or 
                    code.lstrip().startswith('#!') or
                    code.lstrip().startswith('# ')
                )
                if not has_file_header:
                    issues.append(f"{filename}: Missing file header/docstring")
                
                # Check for function docstrings
                func_pattern = r"def\s+\w+\s*\([^)]*\)\s*:"
                functions = re.findall(func_pattern, code)
                if functions:
                    # Simple check: if functions exist but no docstrings, flag it
                    has_docstrings = '"""' in code or "'''" in code
                    if not has_docstrings and len(functions) > 0:
                        issues.append(f"{filename}: Functions without docstrings")
            
            # Check for JavaScript/TypeScript file comments
            elif filename.endswith(('.js', '.jsx', '.ts', '.tsx')):
                has_file_header = code.lstrip().startswith('//') or code.lstrip().startswith('/*')
                if not has_file_header:
                    issues.append(f"{filename}: Missing file header/comment")
        
        return {
            "documentation_issues": issues,
            "properly_documented": len(issues) == 0,
            "issue_count": len(issues)
        }
    
    def _parse_and_save_code(self, response_text: str) -> Dict[str, Any]:
        """
        Parse code blocks from response and save to files.
        DUAL MODE:
        1. PATCH MODE (Copilot-like): Detects SEARCH/REPLACE blocks for atomic edits
        2. FULL FILE MODE (Legacy): Handles code blocks for new files
        """
        # Create (or reuse) a role-based directory so all agents of the same
        # role share a single folder. This ensures backend artifacts end up
        # in one place instead of per-agent folders, and allows agents to
        # read/modify files created by other instances of the same role.
        if self.agent_dir is None:
            # e.g. ./generated_code/backend_engineer/
            self.agent_dir = OUTPUT_DIR / f"{self.role.value}"
            self.agent_dir.mkdir(exist_ok=True, parents=True)
        
        # === MODE 1: CHECK FOR ATOMIC EDITS (PATCH MODE) ===
        search_replace_blocks = PatchApplier.detect_search_replace_blocks(response_text)
        
        if search_replace_blocks:
            logger.info(f"🔧 [PATCH MODE] {self.agent_id} applying {len(search_replace_blocks)} atomic edit(s)")
            patches_applied = 0
            patch_failures = 0
            malformed_blocks = 0
            
            for filename, search_text, replace_text in search_replace_blocks:
                if not PatchApplier.is_valid_patch_filename(filename):
                    malformed_blocks += 1
                    patch_failures += 1
                    warning = (
                        "Malformed SEARCH/REPLACE block detected. "
                        f"Filename '{filename}' is invalid. Use format: <<<<<<< SEARCH\\nfilename.ext"
                    )
                    logger.warning(f"❌ [PATCH MALFORMED] {warning}")
                    self.message_history.append({"role": "system", "content": warning})
                    continue

                file_path = self.agent_dir / filename
                
                # Create change log entry
                operation = EditOperation(
                    agent_id=self.agent_id,
                    iteration=self.iteration_count,
                    filename=filename,
                    operation_type="PATCH"
                )
                
                # Apply patch
                success, old_content, new_content = PatchApplier.apply_patch(file_path, search_text, replace_text)
                
                if success:
                    operation.status = "APPLIED"
                    operation.old_content = old_content
                    operation.new_content = new_content
                    self.generated_code[filename] = new_content
                    patches_applied += 1
                    logger.info(f"✅ [PATCH] {filename}: {len(search_text)} chars → {len(replace_text)} chars")
                    if self.cosmos_manager and PERSIST_CODE_TO_DB:
                        self.cosmos_manager.save_code_artifact(
                            project_id=self.project_context.get("project_id", "unknown"),
                            agent_id=self.agent_id,
                            role=self.role.value,
                            filename=filename,
                            content=new_content,
                            source="patch",
                        )
                else:
                    operation.status = "FAILED"
                    operation.error_message = new_content  # Contains error message
                    logger.warning(f"❌ [PATCH FAILED] {filename}: {new_content}")
                    patch_failures += 1
                    # Don't raise - continue with other patches
                
                # Store operation for audit trail
                if hasattr(self, 'change_logs'):
                    if filename not in self.change_logs:
                        self.change_logs[filename] = FileChangeLog(filename, self.agent_id, 
                                                                   self.project_context.get("project_id"))
                    self.change_logs[filename].add_change(operation)
            
            if patches_applied > 0:
                logger.info(f"✅ [PATCHES APPLIED] {self.agent_id}: {patches_applied}/{len(search_replace_blocks)}")
                asyncio.create_task(self.blackboard_manager.broadcast_to_central(
                    self.agent_id,
                    {
                        "title": f"Code patched by {self.role.value}",
                        "patches": patches_applied,
                        "files": [fn for fn, _, _ in search_replace_blocks]
                    },
                    priority="high"
                ))
            return {
                "mode": "patch",
                "patches_detected": len(search_replace_blocks),
                "patches_applied": patches_applied,
                "patch_failures": patch_failures,
                "malformed_blocks": malformed_blocks,
                "files": [fn for fn, _, _ in search_replace_blocks],
            }
        
        # === MODE 2: FULL FILE GENERATION (LEGACY) ===
        logger.info(f"📝 [FULL FILE MODE] {self.agent_id} generating new code")
        
        # Find all code blocks: ```filename.ext\n...\n```
        pattern = r'```([^\n]+)\n(.*?)\n```'
        matches = list(re.finditer(pattern, response_text, re.DOTALL))
        
        # Validate that response contains at least one code block
        if not matches:
            raise ValueError(f"No code blocks found in response. Response must include at least one code block formatted as: ```filename.ext\ncode here\n```")
        
        files_saved = 0
        saved_files: List[str] = []
        for match in matches:
            filename = match.group(1).strip()
            # Skip JSON blocks (those are metadata)
            if filename.lower() == "json":
                continue
            code_content = match.group(2)
            
            # Save to local file
            filepath = self.agent_dir / filename
            filepath.parent.mkdir(exist_ok=True, parents=True)
            filepath.write_text(code_content)
            
            self.generated_code[filename] = code_content
            files_saved += 1
            saved_files.append(filename)
            logger.info(f"💾 [CODE] {self.role.value[:15]} saved: {filename} ({len(code_content)} bytes)")
            
            # Publish to shared artifacts under role namespace (no per-agent folders)
            artifact_name = f"{self.role.value}/{filename}"
            self.comm_hub.shared_artifacts[artifact_name] = code_content
            
            # Create change log entry for full file creation
            operation = EditOperation(
                agent_id=self.agent_id,
                iteration=self.iteration_count,
                filename=filename,
                operation_type="CREATE",
                new_content=code_content
            )
            operation.status = "APPLIED"
            
            if not hasattr(self, 'change_logs'):
                self.change_logs = {}
            if filename not in self.change_logs:
                self.change_logs[filename] = FileChangeLog(filename, self.agent_id,
                                                          self.project_context.get("project_id"))
            self.change_logs[filename].add_change(operation)

            if self.cosmos_manager and PERSIST_CODE_TO_DB:
                self.cosmos_manager.save_code_artifact(
                    project_id=self.project_context.get("project_id", "unknown"),
                    agent_id=self.agent_id,
                    role=self.role.value,
                    filename=filename,
                    content=code_content,
                    source="full_file",
                )
        
        if files_saved > 0:
            logger.info(f"✅ [GENERATED] {self.role.value[:15]} created {files_saved} file(s)")
            # Broadcast to team that files are ready
            asyncio.create_task(self.blackboard_manager.broadcast_to_central(
                self.agent_id,
                {
                    "title": f"Code generated by {self.role.value}",
                    "files": list(self.generated_code.keys()),
                    "count": files_saved
                },
                priority="high"
            ))
        return {
            "mode": "full_file",
            "files_saved": files_saved,
            "files": saved_files,
        }
    
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
            "status": self.status.value,
            "created_at": self.created_at,
            "dependencies": self.dependencies,
            "files_generated": list(self.generated_code.keys()),
            "metadata": self.outputs,
            "iterations": self.iteration_count,
            "message_history_length": len(self.message_history)
        }

# ==========================================
# 6.5. COPILOT-LIKE EDIT SYSTEM [NEW]
# ==========================================
class SearchReplaceBlock:
    """
    Represents an atomic edit (search/replace) operation.
    Enables Copilot-like surgical edits instead of full file regeneration.
    """
    def __init__(self, filename: str, search_text: str, replace_text: str):
        self.filename = filename
        self.search_text = search_text
        self.replace_text = replace_text
        self.applied = False
        self.error = None
    
    def to_dict(self) -> Dict:
        return {
            "filename": self.filename,
            "search_text_length": len(self.search_text),
            "replace_text_length": len(self.replace_text),
            "applied": self.applied,
            "error": self.error
        }

class EditOperation:
    """
    Represents a single edit operation with metadata for undo/redo.
    Tracks agent, iteration, timestamp, and full change details.
    """
    def __init__(self, agent_id: str, iteration: int, filename: str, 
                 operation_type: str, old_content: str = "", new_content: str = ""):
        self.id = str(uuid.uuid4())[:8]
        self.agent_id = agent_id
        self.iteration = iteration
        self.filename = filename
        self.operation_type = operation_type  # "CREATE", "PATCH", "REPLACE"
        self.old_content = old_content
        self.new_content = new_content
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.status = "PENDING"  # PENDING, APPLIED, FAILED
        self.error_message = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "iteration": self.iteration,
            "filename": self.filename,
            "operation_type": self.operation_type,
            "timestamp": self.timestamp,
            "status": self.status,
            "error_message": self.error_message,
            "old_content_hash": hash(self.old_content) if self.old_content else None,
            "new_content_hash": hash(self.new_content) if self.new_content else None
        }

class FileChangeLog:
    """
    Maintains history of all changes to a file.
    Enables undo/redo and debugging of file evolution.
    """
    def __init__(self, filename: str, agent_id: str, project_id: str):
        self.filename = filename
        self.agent_id = agent_id
        self.project_id = project_id
        self.changes: List[EditOperation] = []
        self.current_content = ""
        self.created_at = datetime.now(timezone.utc).isoformat()
    
    def add_change(self, operation: EditOperation):
        """Record a change operation."""
        self.changes.append(operation)
    
    def get_history(self) -> List[Dict]:
        """Get all changes for audit trail."""
        return [op.to_dict() for op in self.changes]
    
    def can_undo(self) -> bool:
        """Check if undo is available."""
        return len(self.changes) > 0 and self.changes[-1].status == "APPLIED"
    
    def undo_last(self) -> Optional[EditOperation]:
        """Return the last change for potential undo."""
        if self.can_undo():
            return self.changes[-1]
        return None
    
    def to_dict(self) -> Dict:
        return {
            "filename": self.filename,
            "agent_id": self.agent_id,
            "project_id": self.project_id,
            "created_at": self.created_at,
            "change_count": len(self.changes),
            "changes": self.get_history()
        }

class PatchApplier:
    """
    Applies atomic edits (patches) to files.
    Handles search/replace blocks and validates results.
    """
    
    @staticmethod
    def detect_search_replace_blocks(response_text: str) -> List[Tuple[str, str, str]]:
        """
        Detect SEARCH/REPLACE blocks in agent response.
        Returns: List of (filename, search_text, replace_text)
        
        Expected format:
        <<<<<<< SEARCH
        filename.py
            def old():
                pass
        =======
            def new():
                pass
        >>>>>>> REPLACE
        """
        pattern = r'<<<<<<< SEARCH\s+([^\n]+)\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE'
        matches = re.finditer(pattern, response_text, re.DOTALL | re.MULTILINE)
        
        blocks = []
        for match in matches:
            filename = match.group(1).strip()
            search_text = match.group(2)
            replace_text = match.group(3)
            blocks.append((filename, search_text, replace_text))
        
        return blocks

    @staticmethod
    def is_valid_patch_filename(filename: str) -> bool:
        """Basic filename validation for SEARCH/REPLACE blocks."""
        name = filename.strip()
        if not name or name.startswith("/") or ".." in name:
            return False
        if any(ch in name for ch in ("(", ")", "{", "}", ":", ";")):
            return False
        # Require likely file shape for patch target.
        return "." in name
    
    @staticmethod
    def apply_patch(file_path: Path, search_text: str, replace_text: str) -> Tuple[bool, str, str]:
        """
        Apply a single search/replace patch to a file.
        Returns: (success, old_content, new_content)
        """
        try:
            if not file_path.exists():
                return False, "", f"File not found: {file_path}"
            
            with open(file_path, 'r') as f:
                old_content = f.read()
            
            # Check if search_text exists
            if search_text not in old_content:
                # Try to find similar content (fuzzy match)
                logger.warning(f"⚠️  Exact search text not found in {file_path.name}. Attempting fuzzy match...")
                return False, old_content, f"Search text not found in file"
            
            # Apply patch
            new_content = old_content.replace(search_text, replace_text, 1)  # Replace only first occurrence
            
            # Validate syntax for Python files
            if file_path.suffix == '.py':
                try:
                    ast.parse(new_content)
                except SyntaxError as e:
                    return False, old_content, f"Syntax error after patch: {e}"
            
            # Write back
            with open(file_path, 'w') as f:
                f.write(new_content)
            
            return True, old_content, new_content
        
        except Exception as e:
            return False, "", f"Error applying patch: {str(e)}"

# ==========================================
# 7. SWARM ORCHESTRATOR (Replaces DAG) [NEW]
# ==========================================
class SwarmOrchestrator:
    """
    Orchestrates agents in a swarm pattern instead of rigid DAG.
    Agents can handoff work dynamically, pause for user input, and iterate.
    Replaces the old parallel_execution_groups approach.
    """
    
    def __init__(self, collaboration_bus: CollaborationBus, checkpoint_manager: CheckpointManager):
        self.collaboration_bus = collaboration_bus
        self.checkpoint_manager = checkpoint_manager
        self.role_resolver: Optional[RoleResolver] = None
        self.active_agents: Dict[str, Agent] = {}
        self.completed_agents: Dict[str, Agent] = {}
        self.paused_agents: Dict[str, Agent] = {}
        self.execution_log: List[Dict] = []
        self.running_tasks: Dict[str, asyncio.Task] = {}
    
    async def launch_swarm(self, agents: Dict[str, Agent], task_context: Dict, 
                          max_concurrent: int = 5, timeout_per_agent: float = 300) -> Dict:
        """
        Launch agents in a swarm. They coordinate dynamically via handoffs and RFCs.
        No predetermined execution order - agents decide what they need from each other.
        """
        logger.info(f"🐝 Launching swarm of {len(agents)} agents...")
        self.active_agents = agents.copy()
        
        # Initialize RoleResolver for handoff routing
        self.role_resolver = RoleResolver(agents)
        self.collaboration_bus.set_role_resolver(self.role_resolver)
        logger.info("🔀 Role resolver initialized for intelligent handoff routing")

        setup_agents = {
            agent_id: agent for agent_id, agent in agents.items()
            if agent.role.value in SETUP_PHASE_ROLES
        }
        coding_agents = {
            agent_id: agent for agent_id, agent in agents.items()
            if agent.role.value in CODING_PHASE_ROLES
        }
        other_agents = {
            agent_id: agent for agent_id, agent in agents.items()
            if agent.role.value not in SETUP_PHASE_ROLES and agent.role.value not in CODING_PHASE_ROLES
        }

        logger.info(
            f"🚦 Strict phase execution: setup={len(setup_agents)}, coding={len(coding_agents)}, other={len(other_agents)}"
        )
        if setup_agents:
            await self._execute_batch(setup_agents, task_context, timeout_per_agent, "setup")
        setup_failed = any(agent.status == AgentStatus.FAILED for agent in setup_agents.values())

        if setup_failed:
            logger.error("❌ Setup phase failed. Coding phase blocked.")
        else:
            to_run = {}
            to_run.update(coding_agents)
            to_run.update(other_agents)
            if to_run:
                await self._execute_batch(to_run, task_context, timeout_per_agent, "coding")

        for agent_id, agent in agents.items():
            self._record_agent_result(agent_id, agent)
        logger.info(f"📡 Service Bus publish health: {ServiceBusPublisher.health_snapshot()}")
        
        return {
            "completed": len(self.completed_agents),
            "paused": len(self.paused_agents),
            "failed": len([a for a in agents.values() if a.status == AgentStatus.FAILED]),
            "execution_log": self.execution_log,
            "collaboration_bus": {
                "handoffs": len(self.collaboration_bus.handoffs),
                "rfcs": len(self.collaboration_bus.rfcs)
            },
            "setup_phase_failed": setup_failed,
        }

    async def _execute_batch(
        self,
        batch_agents: Dict[str, Agent],
        task_context: Dict,
        timeout_per_agent: float,
        phase_name: str,
    ):
        tasks = [self._run_agent_with_timeout(agent, task_context, timeout_per_agent) for agent in batch_agents.values()]
        logger.info(f"🚀 Executing {len(tasks)} agent(s) in {phase_name} phase...")
        await asyncio.gather(*tasks, return_exceptions=True)

    def _record_agent_result(self, agent_id: str, agent: Agent):
        if agent.status == AgentStatus.COMPLETED:
            self.completed_agents[agent_id] = agent
        elif agent.status == AgentStatus.PAUSED:
            self.paused_agents[agent_id] = agent

        self.execution_log.append({
            "agent_id": agent_id,
            "status": agent.status.value,
            "iterations": agent.iteration_count,
            "files_generated": len(agent.generated_code),
        })
    
    async def _run_agent_with_timeout(self, agent: Agent, task_context: Dict, timeout: float) -> Dict:
        """Run a single agent with timeout protection."""
        self.running_tasks[agent.agent_id] = asyncio.current_task()
        try:
            result = await asyncio.wait_for(
                agent.execute_iteratively(task_context),
                timeout=timeout
            )
            return result
        except asyncio.TimeoutError:
            logger.warning(f"⏱️  Agent {agent.agent_id} timed out after {timeout}s")
            agent.status = AgentStatus.BLOCKED
            return {"status": "timeout", "agent_id": agent.agent_id}
        except Exception as e:
            logger.error(f"❌ Agent {agent.agent_id} error: {e}")
            agent.status = AgentStatus.FAILED
            return {"status": "failed", "agent_id": agent.agent_id, "error": str(e)}
        finally:
            self.running_tasks.pop(agent.agent_id, None)

    async def rerun_agents(
        self,
        agents: Dict[str, Agent],
        task_context: Dict,
        timeout_per_agent: float,
        instruction: str,
        target_roles: Optional[Set[str]] = None,
        selector: Optional[str] = None,
    ) -> Dict[str, int]:
        """Re-activate selected agents and schedule fresh iterative runs."""
        target_roles = target_roles or set()
        matched: List[Agent] = []
        for agent in agents.values():
            by_selector = bool(selector and (selector == agent.agent_id or selector == agent.role.value))
            by_role = bool(target_roles and agent.role.value in target_roles)
            if by_selector or by_role:
                matched.append(agent)

        scheduled = 0
        for agent in matched:
            if agent.agent_id in self.running_tasks:
                continue
            if agent.status not in {AgentStatus.COMPLETED, AgentStatus.WAITING_FOR_RESPONSE, AgentStatus.PAUSED, AgentStatus.FAILED}:
                continue
            # Exhausted agents must be reset, otherwise they immediately re-hit max-iteration guard.
            if agent.iteration_count >= MAX_AGENT_ITERATIONS:
                agent.iteration_count = 0
                agent.last_error = None
                agent.status = AgentStatus.CREATED
                agent.message_history.append({
                    "role": "system",
                    "content": f"Rerun reset applied after max iterations ({MAX_AGENT_ITERATIONS}). Continue with clean filenames and required deliverables.",
                })
            agent.message_history.append({
                "role": "user",
                "content": f"Runtime instruction: {instruction}",
            })
            agent.status = AgentStatus.IN_PROGRESS
            agent.work_completed = False
            task = asyncio.create_task(self._run_agent_with_timeout(agent, task_context, timeout_per_agent))
            self.running_tasks[agent.agent_id] = task
            scheduled += 1
        return {"matched_agents": len(matched), "scheduled_agents": scheduled}
    
    async def resume_paused_agents(self, user_responses: Dict[str, str]) -> Dict:
        """
        Resume paused agents after receiving user feedback.
        user_responses: {agent_id: "user's response to the pause question"}
        """
        logger.info(f"🔄 Resuming {len(user_responses)} paused agent(s)...")
        
        results = {}
        for agent_id, response in user_responses.items():
            if agent_id not in self.paused_agents:
                logger.warning(f"⚠️  Agent {agent_id} not found in paused agents")
                continue
            
            agent = self.paused_agents[agent_id]
            logger.info(f"▶️  Resuming {agent_id}...")
            
            # Add user response to message history
            agent.message_history.append({
                "role": "user",
                "content": f"User feedback: {response}"
            })
            
            # Resume execution
            agent.status = AgentStatus.IN_PROGRESS
            result = await agent.execute_iteratively({})
            results[agent_id] = result
            
            if agent.status == AgentStatus.COMPLETED:
                del self.paused_agents[agent_id]
                self.completed_agents[agent_id] = agent
        
        return results

# ==========================================
# 7. AZURE INFRASTRUCTURE MANAGERS
# ==========================================
class AgentSpawner:
    """
    Responsible for instantiating agents based on task ledger specifications
    and managing their lifecycle in the system. Updated for swarm mode.
    """
    
    def __init__(self, cosmos_manager, comm_hub: AgentCommunicationHub, 
                 collaboration_bus: CollaborationBus, checkpoint_manager: CheckpointManager,
                 blackboard_manager: BlackboardManager, audit_logger: 'AuditLogger' = None,
                 requirements_manager: 'RequirementsManager' = None):
        self.cosmos_manager = cosmos_manager
        self.comm_hub = comm_hub
        self.collaboration_bus = collaboration_bus
        self.checkpoint_manager = checkpoint_manager
        self.blackboard_manager = blackboard_manager
        self.audit_logger = audit_logger  # NEW
        self.requirements_manager = requirements_manager  # NEW
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
                        collaboration_bus=self.collaboration_bus,
                        checkpoint_manager=self.checkpoint_manager,
                        blackboard_manager=self.blackboard_manager,
                        cosmos_manager=self.cosmos_manager,
                        dependencies=agent_spec.get("dependencies", []),
                        audit_logger=self.audit_logger,  # NEW
                        requirements_manager=self.requirements_manager  # NEW
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
        LEGACY METHOD - Kept for backward compatibility.
        Use SwarmOrchestrator.launch_swarm() for new swarm-based execution.
        
        Execute agents respecting their dependencies using the DAG structure.
        """
        logger.info("⚙️  WARNING: Using legacy DAG execution. Consider using SwarmOrchestrator instead.")
        execution_results = {}
        executed_roles: Set[str] = set()
        
        for group in parallel_groups:
            logger.info(f"🔄 Executing parallel group: {group}")
            tasks = []
            group_agents = []
            
            for role_name in group:
                agents_for_role = [
                    agent for agent in self.agents.values()
                    if agent.role.value == role_name
                ]
                
                if not agents_for_role:
                    logger.warning(f"⚠️  No agents found for role: {role_name}")
                    continue
                
                role_dependencies = dag.get(role_name, [])
                if not all(dep_role in executed_roles for dep_role in role_dependencies):
                    logger.warning(f"⚠️  Skipping {role_name} - dependencies not satisfied: {role_dependencies}")
                    continue
                
                for agent in agents_for_role:
                    dependencies_output = {}
                    for dep_role in role_dependencies:
                        dep_agents = [a for a in self.agents.values() if a.role.value == dep_role]
                        dependencies_output[dep_role] = [a.outputs for a in dep_agents]
                    
                    task_context = {
                        "agent_role": role_name,
                        "dependencies_output": dependencies_output
                    }
                    tasks.append(agent.execute_iteratively(task_context))
                    group_agents.append(agent)
            
            if tasks:
                logger.info(f"🚀 Executing {len(tasks)} agent(s) in parallel...")
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for agent, result in zip(group_agents, results):
                    execution_results[agent.agent_id] = result
                    executed_roles.add(agent.role.value)
        
        logger.info(f"✅ Agent execution completed. Executed roles: {executed_roles}")
        logger.info(f"\n📁 Generated code saved to: {OUTPUT_DIR.absolute()}")
        
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
        self.exchange_log_container = self.db.create_container_if_not_exists(
            id=EXCHANGE_LOG_CONTAINER,
            partition_key=PartitionKey(path="/project_id")
        )
        # NEW: Container for final code artifacts
        self.final_code_container = self.db.create_container_if_not_exists(
            id="FinalCodeArtifacts",
            partition_key=PartitionKey(path="/project_id")
        )
        logger.info("✔️  Cosmos DB initialized")

    def _make_doc_id(self, prefix: str, *parts: str) -> str:
        clean = "_".join(str(p).replace("/", "_").replace(" ", "_") for p in parts if p is not None)
        return f"{prefix}_{clean}"

    def _base_doc(self, project_id: str, doc_type: str, doc_name: str) -> Dict[str, Any]:
        return {
            "project_id": project_id,
            "type": doc_type,  # backward-compatible field
            "doc_type": doc_type,
            "doc_name": doc_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def save_ledger(self, ledger_data: Dict):
        self.ledger_container.upsert_item(ledger_data)
        logger.info(f"✔️  Ledger {ledger_data['project_id']} persisted to Cosmos DB.")

    def save_agent_registry(self, project_id: str, agents: Dict[str, Agent]):
        """Save agent registry to Cosmos DB for future reference."""
        agent_records = {
            "id": self._make_doc_id("log_agent_registry", project_id),
            **self._base_doc(project_id, "log.agent_registry", "agent_registry"),
            "agents": [agent.to_dict() for agent in agents.values()],
            "total_agents": len(agents)
        }
        self.agent_container.upsert_item(agent_records)
        logger.info(f"✔️  Agent registry saved for project {project_id}")

    def save_blackboard_message(self, project_id: str, blackboard_name: str, message: Dict):
        """Save blackboard message to exchange log."""
        exchange_record = {
            "id": self._make_doc_id("log_blackboard", project_id, message.get("id")),
            **self._base_doc(project_id, "log.blackboard", f"blackboard_{blackboard_name}"),
            "blackboard_name": blackboard_name,
            "from_agent": message.get("from_agent"),
            "timestamp": message.get("timestamp"),
            "priority": message.get("priority"),
            "content": message.get("message"),
            "message_id": message.get("id")
        }
        self.exchange_log_container.upsert_item(exchange_record)

    def save_handoff(self, project_id: str, handoff: 'Handoff'):
        """Save handoff communication to exchange log."""
        exchange_record = {
            "id": self._make_doc_id("log_handoff", project_id, handoff.id),
            **self._base_doc(project_id, "log.handoff", "handoff_event"),
            "from_agent": handoff.from_agent,
            "to_agent": handoff.to_agent,
            "timestamp": handoff.created_at,
            "status": handoff.status,
            "context": handoff.context,
            "handoff_id": handoff.id
        }
        self.exchange_log_container.upsert_item(exchange_record)

    def save_rfc(self, project_id: str, rfc: 'RequestForComment'):
        """Save RFC communication to exchange log."""
        exchange_record = {
            "id": self._make_doc_id("log_rfc", project_id, rfc.id),
            **self._base_doc(project_id, "log.rfc", "rfc_event"),
            "author": rfc.author,
            "timestamp": rfc.created_at,
            "title": rfc.title,
            "description": rfc.description,
            "tags": rfc.tags,
            "rfc_id": rfc.id
        }
        self.exchange_log_container.upsert_item(exchange_record)

    async def save_blackboard_post(self, project_id: str, post: Dict):
        """Save a blackboard post to Cosmos DB."""
        try:
            post_record = {
                "id": self._make_doc_id("log_blackboard_post", project_id, post.get("id")),
                **self._base_doc(project_id, "log.blackboard_post", "blackboard_post"),
                "sender_id": post.get("sender_id"),
                "sender_role": post.get("sender_role"),
                "target_group": post.get("target_group"),
                "content": post.get("content"),
                "post_type": post.get("post_type"),
                "timestamp": post.get("timestamp"),
                "visible_to_roles": post.get("visible_to_roles", [])
            }
            self.exchange_log_container.upsert_item(post_record)
            logger.debug(f"💾 Blackboard post saved: {post.get('id')}")
        except Exception as e:
            logger.warning(f"⚠️  Error saving blackboard post: {e}")

    async def save_message_history(self, project_id: str, agent_id: str, iteration: int, messages: List[Dict]):
        """Save agent message history after each iteration to enable resumption."""
        try:
            history_doc = {
                "id": self._make_doc_id("log_message_history", project_id, agent_id, str(iteration)),
                **self._base_doc(project_id, "log.message_history", f"message_history_{agent_id}"),
                "agent_id": agent_id,
                "iteration": iteration,
                "message_count": len(messages)
            }
            self.exchange_log_container.upsert_item(history_doc)
            logger.debug(f"💾 Message history saved for {agent_id} iteration {iteration}")
        except Exception as e:
            logger.warning(f"⚠️  Error saving message history: {e}")

    async def save_file_change_log(self, project_id: str, agent_id: str, filename: str, change_log: 'FileChangeLog'):
        """Save file change history for audit trail and undo capability."""
        try:
            changelog_doc = {
                "id": self._make_doc_id("log_file_change", project_id, agent_id, filename),
                **self._base_doc(project_id, "log.file_change", f"file_change_{filename}"),
                "agent_id": agent_id,
                "filename": filename,
                "created_at": change_log.created_at,
                "change_count": len(change_log.changes),
                "changes": change_log.get_history()[-10:]  # Keep last 10 for brevity
            }
            self.exchange_log_container.upsert_item(changelog_doc)
            logger.debug(f"💾 File changelog saved for {agent_id}: {filename}")
        except Exception as e:
            logger.warning(f"⚠️  Error saving file changelog: {e}")

    def save_final_code_artifact(
        self,
        project_id: str,
        agent_id: str,
        role: str,
        filename: str,
        content: str,
        iteration: int
    ):
        """Save final version of code file when agent completes."""
        try:
            # Determine semantic prefix
            semantic_prefix = "artifact"
            ext = Path(filename).suffix.lower()
            
            if ext in {'.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.go', '.cs', '.rb'}:
                semantic_prefix = "code"
            elif ext in {'.yml', '.yaml', '.json', '.tf', '.dockerfile'}:
                semantic_prefix = "config"
            elif ext in {'.md', '.rst', '.txt', '.adoc'}:
                semantic_prefix = "docs"
            elif ext in {'.sql', '.ddl'}:
                semantic_prefix = "schema"
            
            final_artifact = {
                "id": self._make_doc_id("final_code", project_id, role, filename),
                **self._base_doc(project_id, "final_code_artifact", filename),
                "agent_id": agent_id,
                "role": role,
                "filename": filename,
                "content": content,
                "content_length": len(content),
                "iteration_finalized": iteration,
                "semantic_type": semantic_prefix,
                "artifact_name": f"{semantic_prefix}_{filename}"
            }
            self.final_code_container.upsert_item(final_artifact)
            logger.info(f"💾 [FINAL] {semantic_prefix}_{filename} stored in Cosmos DB (project: {project_id})")
        except Exception as e:
            logger.warning(f"⚠️  Error saving final code artifact: {e}")

    def save_code_artifact(
        self,
        project_id: str,
        agent_id: str,
        role: str,
        filename: str,
        content: str,
        source: str,
    ):
        """Persist generated code artifact with explicit artifact typing."""
        try:
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

            # Determine semantic artifact prefix based on file extension
            ext = filename.split('.')[-1].lower() if '.' in filename else ''
            if ext in ('py', 'js', 'ts', 'jsx', 'tsx', 'java', 'go', 'cs', 'rb'):
                prefix = 'code'
            elif ext in ('yml', 'yaml', 'json', 'tf', 'dockerfile'):
                prefix = 'config'
            elif ext in ('md', 'rst', 'txt', 'adoc'):
                prefix = 'docs'
            elif ext in ('sql', 'ddl'):
                prefix = 'schema'
            elif ext in ('log',):
                prefix = 'log'
            elif ext in ('spec', 'test') or filename.lower().startswith('test_'):
                prefix = 'test'
            else:
                prefix = 'artifact'

            artifact_name = f"{prefix}_{filename}"
            artifact_doc = {
                "id": self._make_doc_id("artifact", project_id, agent_id, artifact_name, source),
                **self._base_doc(project_id, f"artifact.{prefix}", artifact_name),
                "agent_id": agent_id,
                "role": role,
                "filename": filename,
                "artifact_name": artifact_name,
                "prefix": prefix,
                "source": source,
                "content_hash": content_hash,
                "content": content,
            }
            self.exchange_log_container.upsert_item(artifact_doc)
        except Exception as e:
            logger.warning(f"⚠️  Error saving code artifact {filename}: {e}")

class Orchestrator:
    """Handles Ghost Handshakes and agent coordination via Service Bus [cite: 431, 432]."""
    
    @staticmethod
    async def publish_ghost_handshake(agent_name: str, schema_stub: Dict):
        published = await ServiceBusPublisher.publish_json(
            "queue",
            GHOST_HANDSHAKE_QUEUE,
            {
                "type": "GHOST_HANDSHAKE",
                "source_agent": agent_name,
                "stub": schema_stub,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        if published:
            logger.info(f"👻 Ghost Handshake published for {agent_name}.")
        else:
            logger.info(f"ℹ️  Ghost Handshake queue publish skipped/unavailable for {agent_name}.")

    @staticmethod
    async def publish_agent_coordination_event(event_type: str, data: Dict):
        """Publish agent coordination events for cross-team communication."""
        published = await ServiceBusPublisher.publish_json(
            "queue",
            AGENT_EXECUTION_QUEUE,
            {
                "event_type": event_type,
                "data": data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        if published:
            logger.info(f"📢 Coordination event published: {event_type}")

# ==========================================
# 9. MAIN EXECUTION FLOW
# ==========================================
async def main(user_input: str = None, project_name: str = None, owner_id: str = "api_user"):
    """
    Main orchestration entry point
    
    Args:
        user_input: User's project description/requirements
        project_name: Optional project name
        owner_id: User/owner identifier
    """
    logger.info("🚀 Initializing Agentic Nexus Platform...")
    
    # Use provided input or default example
    if user_input is None:
        user_input = """Build a collaborative platform where users can share, view, analyse and upload legal documents. Please choose and decide appropriate architecture and tech stack. There should be no ML or Devops."""
    
    # Initialize systems with NEW SWARM ARCHITECTURE
    ledger = TaskLedger(user_input, owner_id)
    director = DirectorAI()
    cosmos = CosmosManager()
    comm_hub = AgentCommunicationHub(cosmos)
    
    # Initialize Requirements Manager and Audit Logger [NEW]
    requirements_manager = RequirementsManager()
    audit_logger = AuditLogger()
    
    logger.info(f"📝 Requirements Manager initialized at: {requirements_manager.requirements_dir}")
    logger.info(f"📊 Audit Logger initialized at: {audit_logger.logs_dir}")
    
    # Get project_id early (generated by ledger)
    ledger_data = await director.clarify_intent(ledger)
    project_id = ledger_data.get("project_id")
    
    # Override project name if provided
    if project_name:
        ledger_data["project_name"] = project_name
        ledger.data["project_name"] = project_name
    
    collaboration_bus = CollaborationBus(cosmos_manager=cosmos, project_id=project_id)  # NEW: Shared bus with persistence
    checkpoint_manager = CheckpointManager(cosmos)  # NEW: State persistence
    blackboard_manager = BlackboardManager(cosmos_manager=cosmos, project_id=project_id)  # NEW: Central + group messaging with persistence
    spawner = AgentSpawner(cosmos, comm_hub, collaboration_bus, checkpoint_manager, blackboard_manager,
                          audit_logger=audit_logger, requirements_manager=requirements_manager)  # NEW: Pass managers
    swarm_orchestrator = SwarmOrchestrator(collaboration_bus, checkpoint_manager)  # NEW: Swarm orchestration
    
    try:
        # 2. Director AI analyzes intent and creates comprehensive task ledger
        logger.info("🧠 Director AI analyzing requirements...")
        ledger.data.update(ledger_data)
        ledger.add_revision("Initial intent decomposition and agent planning completed.")
        
        logger.info(f"📋 Task Ledger populated with {len(ledger.data.get('agent_specifications', {}).get('required_agents', []))} agent specifications")
        
        # 3. Save the comprehensive task ledger to Cosmos DB
        cosmos.save_ledger(ledger.data)

        # 4. Build dependency graph before spawn so dependencies are available for setup
        logger.info("📊 Building initial dependency graph...")
        dag, parallel_groups = await director.generate_agent_dag(ledger)
        ledger.data["agent_specifications"]["agent_dependencies"] = dag
        ledger.data["agent_specifications"]["parallel_execution_groups"] = parallel_groups
        cosmos.save_ledger(ledger.data)

        # 5. Spawn agents based on ledger specifications
        logger.info("\n👥 Spawning specialized agents (Swarm Mode)...")
        agents = await spawner.spawn_agents_from_ledger(ledger)
        
        # 6. Optional Service Bus consumer for sync into central blackboard
        await blackboard_manager.start_service_bus_sync()

        # 7. Create GROUP BLACKBOARDS for dependent agents using real agent IDs
        logger.info("🔌 Setting up group blackboards for agent dependencies...")
        role_to_agent_ids: Dict[str, Set[str]] = {}
        for aid, agent in agents.items():
            role_to_agent_ids.setdefault(agent.role.value, set()).add(aid)
        for role, dependencies in dag.items():
            if dependencies:  # If this role has dependencies
                group_name = f"{role}_team"
                member_ids: Set[str] = set()
                member_ids.update(role_to_agent_ids.get(role, set()))
                for dep_role in dependencies:
                    member_ids.update(role_to_agent_ids.get(dep_role, set()))
                if member_ids:
                    await blackboard_manager.create_group_blackboard(group_name, member_ids)
                    logger.info(f"  ✓ Created group blackboard: {group_name}")
                else:
                    logger.warning(f"  ⚠️ Skipped group blackboard {group_name} (no matching agent IDs)")
        
        # 8. Publish PROJECT METADATA to central blackboard
        logger.info("📢 Broadcasting project metadata to all agents...")
        await blackboard_manager.broadcast_to_central(
            "system",
            {
                "title": "Project Initialization",
                "tech_stack": ledger.data.get("technology_stack", {}),
                "requirements": ledger.data.get("functional_requirements", []),
                "project_name": ledger.data.get("project_name", ""),
                "project_id": ledger.data["project_id"]
            },
            priority="critical"
        )

        # 9. Execute agents in SWARM MODE with strict setup->coding phases
        logger.info("\n⚙️  Starting SWARM execution phase...")
        logger.info("💬 Agents will now coordinate dynamically:")
        logger.info("   - Handoff work to other agents as needed")
        logger.info("   - Pause for user input when ambiguous")
        logger.info("   - Post RFCs for team review")
        logger.info("   - Iterate until task completion")
        
        swarm_results = await swarm_orchestrator.launch_swarm(
            agents=agents,
            task_context=ledger.data,
            max_concurrent=MAX_PARALLEL_AGENTS,
            timeout_per_agent=AGENT_TIMEOUT_SECONDS
        )
        
        # 7. Save agent registry and results
        cosmos.save_agent_registry(ledger.data["project_id"], agents)
        
        # 8. Check for paused agents (awaiting user feedback)
        if swarm_orchestrator.paused_agents:
            logger.info(f"\n⏸️  {len(swarm_orchestrator.paused_agents)} agent(s) paused and awaiting user input:")
            for agent_id in swarm_orchestrator.paused_agents.keys():
                logger.info(f"   - {agent_id}")
            logger.info("\nYou can resume these agents by providing feedback via the collaboration bus or API.")
        
        # 9. Publish ghost handshake for backend preparation (pre-emptive stubbing)
        api_stub = {
            "endpoint": "/api/documents",
            "methods": ["GET", "POST", "PUT", "DELETE"],
            "auth": "Bearer JWT",
            "entities": ["Document", "Case", "Organization"]
        }
        await Orchestrator.publish_ghost_handshake("BackendEngineer", api_stub)
        
        # Print comprehensive summary with NEW SWARM METRICS
        logger.info("\n" + "="*70)
        logger.info("✅ AGENTIC NEXUS SWARM EXECUTION COMPLETE")
        logger.info("="*70)
        logger.info(f"Project ID: {ledger.data['project_id']}")
        logger.info(f"Project Name: {ledger.data.get('project_name', 'N/A')}")
        logger.info(f"Agents Spawned: {len(agents)}")
        logger.info(f"Agents Completed: {len(swarm_orchestrator.completed_agents)}")
        logger.info(f"Agents Paused: {len(swarm_orchestrator.paused_agents)}")
        logger.info(f"Total Files Generated: {sum(len(a.generated_code) for a in agents.values())}")
        logger.info("="*70)
        
        logger.info("\n📊 --- SWARM COORDINATION METRICS ---")
        logger.info(f"Total Handoffs Posted: {len(collaboration_bus.handoffs)}")
        logger.info(f"Total RFCs Posted: {len(collaboration_bus.rfcs)}")
        logger.info(f"Total Agent Iterations: {sum(a.iteration_count for a in agents.values())}")
        logger.info(f"Execution Log Entries: {len(swarm_results.get('execution_log', []))}")
        
        logger.info("\n📋 --- UPDATED TASK LEDGER SUMMARY ---")
        summary = {
            "project_id": ledger.data["project_id"],
            "project_name": ledger.data.get("project_name", "N/A"),
            "status": ledger.data["status"],
            "agent_count": len(agents),
            "required_agents": ledger.data["agent_specifications"]["required_agents"],
            "technology_stack": ledger.data.get("technology_stack", {}),
            "non_functional_requirements": ledger.data["non_functional_requirements"],
            "swarm_execution_mode": True,
            "revision_history": ledger.data["revision_history"]
        }
        logger.info("\n" + json.dumps(summary, indent=2))
        
        logger.info("\n👥 --- AGENT EXECUTION RESULTS (SWARM MODE) ---")
        for agent_id, agent in agents.items():
            status_emoji = {"completed": "✅", "paused": "⏸️", "failed": "❌", "in_progress": "🔄"}.get(agent.status.value, "❓")
            files_count = len(agent.generated_code)
            logger.info(f"  {status_emoji} {agent_id} ({agent.status.value}): {files_count} file(s), {agent.iteration_count} iteration(s)")
        
        logger.info(f"\n🏗️  Generated Code Directory Structure:")
        logger.info(f"   📦 {OUTPUT_DIR}/")
        if (OUTPUT_DIR / "agents").exists():
            for role_dir in sorted((OUTPUT_DIR / "agents").iterdir()):
                if role_dir.is_dir():
                    files = list(role_dir.glob("*"))
                    logger.info(f"      📁 {role_dir.name}/ ({len(files)} file(s))")
                    for f in sorted(files)[:5]:  # Show first 5 files
                        logger.info(f"         └─ {f.name}")
                    if len(files) > 5:
                        logger.info(f"         └─ ... and {len(files) - 5} more file(s)")
        
        logger.info(f"\n🐝 SWARM EXECUTION SUMMARY:")
        logger.info(f"   Execution Model: Swarm (Dynamic Coordination)")
        logger.info(f"   Handoff Mechanism: Enabled")
        logger.info(f"   RFC Collaboration: Enabled")
        logger.info(f"   Checkpoint/Pause: Enabled")
        logger.info(f"   Iterative Loops: Enabled")
        logger.info(f"\n🎉 All agents executed in swarm mode with dynamic coordination!")
        logger.info(f"📂 Review: {OUTPUT_DIR.absolute()}")
        
        # NEW: Log summaries of requirements and audit trail
        logger.info("\n" + "="*70)
        logger.info("📋 SHARED REQUIREMENTS FILES GENERATED")
        logger.info("="*70)
        all_requirements = requirements_manager.get_all_requirements()
        for role, content in all_requirements.items():
            lines = len([l for l in content.split('\n') if l.strip() and not l.startswith('#')])
            logger.info(f"✅ {role.replace('_', ' ').title()}: {lines} requirement(s)")
            req_file = requirements_manager.requirements_dir / ROLE_REQUIREMENTS_MAP[role]
            logger.info(f"   📄 {req_file.name}")
        
        logger.info("\n" + "="*70)
        logger.info("📊 AUDIT LOGS & COMMUNICATIONS LOGGED")
        logger.info("="*70)
        ai_responses = len(list(audit_logger.ai_responses_dir.glob("*.log")))
        communications = len(list(audit_logger.communications_dir.glob("*.log")))
        logger.info(f"✅ AI Responses Logged: {ai_responses} files")
        logger.info(f"   📂 {audit_logger.ai_responses_dir}")
        logger.info(f"✅ Inter-Agent Communications Logged: {communications} files")
        logger.info(f"   📂 {audit_logger.communications_dir}")
        logger.info(f"✅ Requirements Changes Logged: requirements.log")
        logger.info(f"   📂 {audit_logger.requirements_log}")
        logger.info(f"✅ Master Audit Log: master_audit.log")
        logger.info(f"   📂 {audit_logger.master_log}")
        logger.info("\n💡 All agent output, communications, and decisions are logged in ./agent_logs/")
        
        # ========================================
        # 10. DEPLOYMENT INTEGRATION
        # ========================================
        logger.info("\n" + "="*70)
        logger.info("🚀 INITIATING POST-GENERATION DEPLOYMENT INTEGRATION")
        logger.info("="*70)
        
        try:
            deployment_results = await run_post_generation_deployment(
                project_id=ledger.data["project_id"],
                app_name=ledger.data.get("project_name", "nexus-app"),
                ledger_data=ledger.data,
                enable_bundle=True,
                enable_blueprint=True,
                enable_cost_estimate=True
            )
            
            logger.info(f"✅ Deployment bundle generated successfully")
            logger.info(f"   Location: ./generated_code/")
            
            if deployment_results.get("deployment_tasks", {}).get("cost_estimate"):
                cost_info = deployment_results["deployment_tasks"]["cost_estimate"].get("estimate", {})
                monthly_cost = cost_info.get("total_monthly_usd", 0)
                logger.info(f"💰 Estimated monthly cost: ${monthly_cost:.2f}")
        
        except Exception as e:
            logger.warning(f"⚠️  Deployment integration skipped: {str(e)}")
            logger.info("   Continue with code review or manual deployment")
        
        # CONDITIONAL INTERACTIVE SHELL (Option B: Environment-Gated)
        if ENABLE_INTERACTIVE_SHELL:
            logger.info("\n" + "="*70)
            logger.info("🎮 LAUNCHING INTERACTIVE CONTROL SHELL")
            logger.info("="*70)
            await run_interactive_shell(
                agents=agents,
                ledger=ledger,
                blackboard_manager=blackboard_manager,
                swarm_orchestrator=swarm_orchestrator,
                project_id=ledger.data["project_id"],
            )
        else:
            logger.info("\n" + "="*70)
            logger.info("✅ AUTONOMOUS EXECUTION COMPLETE")
            logger.info("📊 Final code available in: " + str(OUTPUT_DIR.absolute()))
            logger.info("🔍 To review results, check generated_code/ directory")
            logger.info("💡 To enable interactive shell: ENABLE_INTERACTIVE_SHELL=true")
            logger.info("="*70)
        
    except Exception as e:
        logger.error(f"❌ Fatal error in Agentic Nexus: {e}", exc_info=True)
        raise
    finally:
        await blackboard_manager.stop_service_bus_sync()

if __name__ == "__main__":
    asyncio.run(main())
