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
import sys
import platform

# Cross-platform file locking
try:
    import fcntl
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False
    if platform.system() == "Windows":
        import msvcrt

def acquire_lock(lock_file):
    """Cross-platform file lock acquisition"""
    if HAS_FCNTL:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
    elif platform.system() == "Windows":
        try:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            time.sleep(0.1)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)

def release_lock(lock_file):
    """Cross-platform file lock release"""
    if HAS_FCNTL:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    elif platform.system() == "Windows":
        try:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

def acquire_shared_lock(lock_file):
    """Cross-platform shared file lock acquisition"""
    if HAS_FCNTL:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
    elif platform.system() == "Windows":
        # Windows doesn't have shared locks, use exclusive
        acquire_lock(lock_file)

from general_agent import GeneralAgent, BackendEngineerAgent, FrontendDeveloperAgent, set_blackboard
from issues_tracker import get_issues_tracker, set_issues_tracker, IssuesTracker
from review_agent import ReviewAgent
from service_bus_coordination import ServiceBusCoordinator
from contract_validator import validate_system_architect_contracts
from dotenv import load_dotenv

load_dotenv()


def _detect_repo_root() -> Path:
  env_root = (os.getenv("NEXUS_ROOT_DIR") or "").strip()
  if env_root:
    return Path(env_root).resolve()

  here = Path(__file__).resolve()
  if here.parent.name == "platform-backend" and here.parent.parent.name.startswith("Azure_Hack-"):
    return here.parent.parent.parent

  return here.parent


REPO_ROOT = _detect_repo_root()
WORKSPACE_DIR = str((REPO_ROOT / "workspace").resolve())
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
AGENT_MAX_ATTEMPTS = int(os.getenv("AGENT_MAX_ATTEMPTS", "5"))  # <=0 means unbounded retry attempts
AGENT_MAX_ITERATIONS_MAIN = int(os.getenv("AGENT_MAX_ITERATIONS_MAIN", "90"))
AGENT_MAX_ITERATIONS_FIX = int(os.getenv("AGENT_MAX_ITERATIONS_FIX", "45"))
RUNTIME_SMOKE_TIMEOUT_SECONDS = int(os.getenv("RUNTIME_SMOKE_TIMEOUT_SECONDS", "0"))
FRONTEND_BUILD_TIMEOUT_SECONDS = int(os.getenv("FRONTEND_BUILD_TIMEOUT_SECONDS", "0"))
LAYER_MAX_WAIT_SECONDS = int(os.getenv("LAYER_MAX_WAIT_SECONDS", "0"))
SLEEP_RECHECK_SECONDS = int(os.getenv("SLEEP_RECHECK_SECONDS", "90"))

BACKEND_API_CONTRACT_REL = "contracts/backend_api_contract.json"
FRONTEND_ROUTE_CONTRACT_REL = "contracts/frontend_route_contract.json"
DIRECTORY_STRUCTURE_CONTRACT_REL = "contracts/directory_structure.json"
SYSTEM_ARCHITECT_CONTRACTS = [
  BACKEND_API_CONTRACT_REL,
  FRONTEND_ROUTE_CONTRACT_REL,
  DIRECTORY_STRUCTURE_CONTRACT_REL,
]
DISABLED_AGENT_ROLES = {"security_engineer"}


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
                acquire_lock(lock_file)
                self.messages.append(entry)
                self._write_file()
            finally:
                release_lock(lock_file)
                lock_file.close()
    
    def read_all(self) -> str:
        """Get all messages as string"""
        with self._lock:
            lock_file = open(self.lock_path, "w")
            try:
                acquire_shared_lock(lock_file)
                if not self.messages:
                    return f"Layer {self.layer_number} blackboard is empty."
                result = f"Layer {self.layer_number} Coordination:\n"
                for msg in self.messages:
                    result += f"- [{msg['agent']}]: {msg['content']}\n"
                return result
            finally:
                release_lock(lock_file)
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
            acquire_lock(lock_file)
            
            entry = {
                "agent": agent_name,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "content": content
            }
            
            self.sections[section].append(entry)
            self._write_file()
            return True
        
        finally:
            release_lock(lock_file)
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

⚠️  MANDATORY FILES - YOU MUST WRITE ALL OF THESE OR VERIFICATION WILL FAIL:
  • migrations/schema.sql    ← write_file("migrations/schema.sql", content=<full DDL>)
  • migrations/seed_data.sql ← write_file("migrations/seed_data.sql", content=<INSERT rows>)
  • config/db_config.js
  • config/db_setup.js
  • README.md

DO NOT emit [READY_FOR_VERIFICATION] until ALL five files above have been written via write_file().

SYSTEM ARCHITECT COMPLIANCE (MANDATORY):
  ✅ Read contracts/backend_api_contract.json and contracts/directory_structure.json first
  ✅ Follow System Architect specifications exactly (no guessing, no drift)
  ✅ You may ONLY edit files that already exist in your owned database directory
  ✅ You are NOT allowed to create/delete files outside scaffolded paths

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
❓ Endpoint-to-table mapping unclear? → STOP and request system_architect clarification
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
            role_description="Design comprehensive test suites, validate code quality, and manually test all routes/pages by running servers",
            specific_instructions="""
════════════════════════════════════════════════════════════════════════════════
🔴 CRITICAL: YOU ARE THE SOLE VERIFIER OF ROUTES AND PAGES
════════════════════════════════════════════════════════════════════════════════

The orchestrator no longer uses static route detection (regex analysis).
YOU are now responsible for all validation:

1. START BOTH SERVERS
   ├─ Backend: cd workspace/backend && node app.js (or npm start)
   ├─ Frontend: cd workspace/frontend && npm run dev
   ├─ Wait for both to start successfully
   └─ Note: Ignore API key errors for external services (Stripe, etc.) - focus on route structure

2. MANUALLY TEST EVERY ROUTE AND PAGE
   ├─ For each endpoint in contracts/backend_api_contract.json:
   │  ├─ Call it directly (curl, Postman, fetch)
   │  ├─ Verify status code matches contract
   │  ├─ Verify response body structure matches contract
   │  └─ Document: PASS or FAIL with evidence
   │
   ├─ For each page in contracts/frontend_route_contract.json:
   │  ├─ Navigate to it in running frontend (localhost:3000/path)
   │  ├─ Verify it loads without errors
   │  ├─ Verify layout/components appear
   │  └─ Document: PASS or FAIL with screenshot/evidence

3. IF YOU FIND FAILURES
   ├─ Document the specific endpoint or page that failed
   ├─ Include expected vs actual with evidence
   ├─ Identify which agent should fix it (backend_engineer, frontend_engineer, etc.)
   ├─ POST TO SERVICE BUS TO WAKE UP THAT AGENT using:
   │  └─ post_to_service_bus(destination="backend_engineer", message={...details...})
   └─ That agent will receive your wake-up and fix the issue

4. AGENTS KNOW HOW TO WAKE EACH OTHER
   ✅ Agents have access to: post_to_service_bus() tool
   ✅ They can call it with destination="{role}" and detailed issue info
   ✅ When an agent is woken up, it reruns with the feedback
   ✅ You can wake them too - use this for any failures you find

5. IGNORE THESE (OK TO SKIP)
   ✅ API key errors (Stripe, payment services)
   ✅ Database connection errors (if DB not configured)
   ✅ Missing environment variables for external services
   ✅ These don't affect route/page structure validation

════════════════════════════════════════════════════════════════════════════════
TEST STRUCTURE - RUN SERVERS, NOT JUST UNIT TESTS
════════════════════════════════════════════════════════════════════════════════

Instead of Jest tests, your primary work is:
  1. Start backend: node app.js
  2. Start frontend: npm run dev
  3. Use browser/curl to navigate pages and call endpoints
  4. Document what works and what fails
  5. Wake up agents for failures

You CAN still create Jest tests for isolated logic, but:
  ✅ Primary goal: Runtime validation of all routes/pages working
  ✅ Secondary goal: Unit tests for business logic
  ✅ NOT the goal: Mocking everything - test real running servers

════════════════════════════════════════════════════════════════════════════════
SUCCESS CRITERIA
════════════════════════════════════════════════════════════════════════════════

✅ Both servers start without crashing (ignoring external service errors OK)
✅ Every contract endpoint is callable and returns a response
✅ Every contract page loads and renders without 404s
✅ Page navigation works (clicking links, using routing)
✅ API calls from frontend reach backend successfully
✅ Any failures are documented with specifics
✅ Agents are woken up for failures requiring fixes

════════════════════════════════════════════════════════════════════════════════

═══════════════════════════════════════════════════════════════════════════════
QA ENGINEER WORKFLOW - GENERIC TESTING AND VALIDATION
═══════════════════════════════════════════════════════════════════════════════

SYSTEM ARCHITECT COMPLIANCE (MANDATORY):
  ✅ Treat contracts/backend_api_contract.json, contracts/frontend_route_contract.json,
    and contracts/directory_structure.json as compulsory source of truth.
  ✅ Verify EACH AND EVERY declared endpoint/page/route exists and behaves as specified.
  ✅ If any mismatch is found, report it as a concrete issue with expected vs actual evidence.

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
          "system_architect": {
            "min_files": 3,
            "required_any": [
              ["backend_api_contract.json", "contracts/backend_api_contract.json"],
              ["frontend_route_contract.json", "contracts/frontend_route_contract.json"],
              ["directory_structure.json", "contracts/directory_structure.json"],
              ["README.md", "docs/api/README.md"]
            ],
            "manifest_any": []
          },
          "database_architect": {
            "min_files": 1,
            "required_any": [
              ["database"]
            ],
            "manifest_any": []
          },
          "backend_engineer": {
            "min_files": 1,
            "required_any": [
              ["backend"]
            ],
            "manifest_any": []
          },
          "frontend_engineer": {
            "min_files": 1,
            "required_any": [
              ["frontend"]
            ],
            "manifest_any": []
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

        try:
          self._apply_directory_structure_contract_scaffold()
        except Exception:
          pass

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
        def _normalize_role_alias(role_value: str) -> str:
          role_norm = str(role_value or "").strip().lower().replace(" ", "_")
          # Map all System Architect aliases to system_architect
          system_architect_aliases = {"system_architect", "solution_architect", "system_architect_agent"}
          if role_norm in system_architect_aliases:
            return "system_architect"
          return role_norm

        if isinstance(raw_spec, str):
          role = _normalize_role_alias(raw_spec)
          if not role:
            return None
          return {
            "role": role,
            "description": "",
            "instructions": ""
          }

        if isinstance(raw_spec, dict):
          role = _normalize_role_alias(raw_spec.get("role") or raw_spec.get("agent_name"))
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
        def _normalize_assignee(role: str) -> str:
            r = str(role or "").strip().lower().replace(" ", "_")
            alias_map = {
              "solution_architect": "system_architect",
              "system_architect_agent": "system_architect",
              "system/ops": "system_architect",
              "project_orchestrator": "system_architect",
              "orchestrator": "system_architect",
              "system": "system_architect",
            }
            return alias_map.get(r, r)

        issues_tracker = get_issues_tracker()
        open_issues = issues_tracker.get_open_issues()
        assigned_roles = sorted({
            _normalize_assignee(i.get("assigned_to"))
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

        def _normalize_assignee(role: str) -> str:
            r = str(role or "").strip().lower().replace(" ", "_")
            alias_map = {
              "solution_architect": "system_architect",
              "system_architect_agent": "system_architect",
              "system/ops": "system_architect",
              "project_orchestrator": "system_architect",
              "orchestrator": "system_architect",
              "system": "system_architect",
            }
            return alias_map.get(r, r)

        issues_tracker = get_issues_tracker()
        resolved_count = 0
        for role in roles:
            role_issues = issues_tracker.get_open_issues(assigned_to=_normalize_assignee(role))
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
      if any(k in text for k in ["backend", "system architect", "service", "controller", "route"]):
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
            ledger = json.load(f)
        self._strip_disabled_roles_from_ledger(ledger)
        return ledger

    def _strip_disabled_roles_from_ledger(self, ledger: Dict) -> None:
      """Remove disabled roles from required_agents/layers/dependencies in-memory."""
      if not isinstance(ledger, dict):
        return
      spec = ledger.get("agent_specifications")
      if not isinstance(spec, dict):
        return

      required = spec.get("required_agents")
      if isinstance(required, list):
        cleaned_required = []
        for entry in required:
          if isinstance(entry, str):
            role = entry.strip().lower().replace(" ", "_")
          elif isinstance(entry, dict):
            role = str(entry.get("role") or entry.get("agent_name") or "").strip().lower().replace(" ", "_")
          else:
            continue
          if role in DISABLED_AGENT_ROLES:
            continue
          cleaned_required.append(entry)
        spec["required_agents"] = cleaned_required

      layers = spec.get("layers")
      if isinstance(layers, list):
        cleaned_layers = []
        for layer in layers:
          if isinstance(layer, list):
            normalized = [
              r for r in layer
              if isinstance(r, str)
              and str(r).strip().lower().replace(" ", "_") not in DISABLED_AGENT_ROLES
            ]
            if normalized:
              cleaned_layers.append(normalized)
          elif isinstance(layer, dict):
            layer_agents = layer.get("agents", [])
            if not isinstance(layer_agents, list):
              continue
            filtered_agents = []
            for a in layer_agents:
              if isinstance(a, str):
                role = a.strip().lower().replace(" ", "_")
              elif isinstance(a, dict):
                role = str(a.get("role") or a.get("agent_name") or "").strip().lower().replace(" ", "_")
              else:
                continue
              if role in DISABLED_AGENT_ROLES:
                continue
              filtered_agents.append(a)
            if filtered_agents:
              layer_copy = dict(layer)
              layer_copy["agents"] = filtered_agents
              cleaned_layers.append(layer_copy)
        spec["layers"] = cleaned_layers

      deps = spec.get("agent_dependencies")
      if isinstance(deps, dict):
        cleaned_deps = {}
        for role, dep_list in deps.items():
          role_norm = str(role or "").strip().lower().replace(" ", "_")
          if role_norm in DISABLED_AGENT_ROLES:
            continue
          if isinstance(dep_list, list):
            filtered = [
              d for d in dep_list
              if str(d or "").strip().lower().replace(" ", "_") not in DISABLED_AGENT_ROLES
            ]
          else:
            filtered = []
          cleaned_deps[role] = filtered
        spec["agent_dependencies"] = cleaned_deps
    
    def _build_execution_layers(self) -> List[List[Dict]]:
      """Parse task ledger and build execution layers.

      Preferred format: agent_specifications.layers = [["role1", "role2"], ...]
      Legacy fallback: build from agent_dependencies DAG.
      """
      spec = self.ledger.get("agent_specifications", {})

      def _normalize_layer_role_alias(role_value: str) -> str:
        role_norm = str(role_value or "").strip().lower().replace(" ", "_")
        system_architect_aliases = {
          "system_architect",
          "solution_architect",
          "system_architect_agent",
        }
        if role_norm in system_architect_aliases:
          return "system_architect"
        return role_norm

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
                layer_roles.append(_normalize_layer_role_alias(agent_ref))
              elif isinstance(agent_ref, dict):
                role = agent_ref.get("role")
                if not role:
                  raise ValueError(f"Invalid layer #{idx}: each agent object must include 'role'")
                layer_roles.append(_normalize_layer_role_alias(role))
              else:
                raise ValueError(f"Invalid layer #{idx}: unsupported agent entry type")
          else:
            raise ValueError(f"Invalid layer #{idx}: must be a list or an object with 'agents'")

          if len(layer_roles) == 0:
            raise ValueError(f"Invalid layer #{idx}: must contain at least one agent")
          layer_specs = []
          for role in layer_roles:
            role = _normalize_layer_role_alias(role)
            if role not in agent_map:
              raise ValueError(f"Layer #{idx} references unknown role: {role}")
            if role in seen:
              # Tolerate duplicate aliases resolving to system_architect
              # (e.g., system_architect + solution_architect in director output).
              if role == "system_architect":
                continue
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

      expected_order = ["system_architect", "database_architect", "backend_engineer", "frontend_engineer", "qa_engineer"]
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
      """Load backend API contract as first-class context payload."""
      contract_path = os.path.join(WORKSPACE_DIR, BACKEND_API_CONTRACT_REL)
      if not os.path.exists(contract_path):
        legacy = os.path.join(WORKSPACE_DIR, "contracts", "api_contract.json")
        contract_path = legacy if os.path.exists(legacy) else contract_path
      with open(contract_path, "r", encoding="utf-8", errors="ignore") as f:
        raw = f.read()

      parsed = json.loads(raw)
      route_map = self._extract_contract_route_map(parsed)
      checksum = hashlib.sha256(raw.encode("utf-8")).hexdigest()
      return {
        "path": os.path.relpath(contract_path, WORKSPACE_DIR).replace("\\", "/"),
        "checksum_sha256": checksum,
        "endpoint_count": len(route_map),
        "content": raw,
      }

    def _load_system_architect_contract_context(self, require_all: bool = False) -> Dict:
      """Load all System Architect contracts and embed full payloads in agent context."""
      context = {}
      required_files = [
        ("backend_api_contract", BACKEND_API_CONTRACT_REL),
        ("frontend_route_contract", FRONTEND_ROUTE_CONTRACT_REL),
        ("directory_structure_contract", DIRECTORY_STRUCTURE_CONTRACT_REL),
      ]

      for key, rel_path in required_files:
        abs_path = os.path.join(WORKSPACE_DIR, rel_path)
        if not os.path.exists(abs_path):
          if require_all:
            raise RuntimeError(f"CRITICAL: missing required System Architect contract: {rel_path}")
          continue
        try:
          with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            raw = f.read()
          parsed = json.loads(raw)
          context[key] = {
            "path": rel_path,
            "checksum_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "content": raw,
            "parsed": parsed,
          }
        except Exception as e:
          if require_all:
            raise RuntimeError(f"CRITICAL: invalid System Architect contract {rel_path}: {str(e)}")

      return context

    def _load_directory_structure_contract(self) -> Dict:
      abs_path = os.path.join(WORKSPACE_DIR, DIRECTORY_STRUCTURE_CONTRACT_REL)
      if not os.path.exists(abs_path):
        return {"ok": False, "error": f"missing {DIRECTORY_STRUCTURE_CONTRACT_REL}", "structure": {}}
      payload = self._read_json_file(abs_path)
      if not isinstance(payload, dict):
        return {"ok": False, "error": f"invalid JSON in {DIRECTORY_STRUCTURE_CONTRACT_REL}", "structure": {}}
      normalized = self._normalize_directory_structure_payload(payload)
      if not isinstance(normalized, dict) or not normalized:
        return {
          "ok": False,
          "error": f"unsupported directory structure shape in {DIRECTORY_STRUCTURE_CONTRACT_REL}",
          "structure": {},
        }
      return {"ok": True, "structure": normalized}

    def _normalize_directory_structure_payload(self, payload: Dict) -> Dict:
      """Normalize directory contract to {section: node} shape.

      Supports:
      - {"backend": {...}, ...}
      - {"structure": {...}}
      - {"structure": [ {"name":"backend","type":"directory", ...}, ... ]}
      """
      if not isinstance(payload, dict):
        return {}

      # Shape A: direct section map.
      if any(k in payload for k in ["backend", "frontend", "database"]):
        return payload

      # Shape B: wrapped map under "structure".
      structure = payload.get("structure")
      if isinstance(structure, dict):
        return structure

      # Shape C: node list under "structure".
      if not isinstance(structure, list):
        return {}

      def _collect_paths(node, out: set):
        if isinstance(node, dict):
          p = node.get("path")
          if isinstance(p, str) and p.strip():
            out.add(p.strip().replace("\\", "/").strip("/"))
          for value in node.values():
            if isinstance(value, (dict, list)):
              _collect_paths(value, out)
        elif isinstance(node, list):
          for item in node:
            _collect_paths(item, out)

      section_names = set()
      for item in structure:
        if not isinstance(item, dict):
          continue
        if str(item.get("type", "")).strip().lower() == "directory":
          name = str(item.get("name", "")).strip()
          if name:
            section_names.add(name)

      all_paths = set()
      _collect_paths(structure, all_paths)

      normalized = {name: [] for name in section_names}
      for p in sorted(all_paths):
        parts = p.split("/", 1)
        if len(parts) != 2:
          continue
        section, rel = parts[0], parts[1]
        normalized.setdefault(section, []).append(rel)

      return normalized

    _SCAFFOLD_STUBS = {
      ".sql":  "-- scaffold placeholder: replace with real SQL\n",
      ".md":   "# Scaffold placeholder\n",
      ".js":   "// scaffold placeholder\n",
      ".ts":   "// scaffold placeholder\n",
      ".py":   "# scaffold placeholder\n",
      ".json": "{}\n",
    }

    def _touch_file_if_missing(self, abs_path: str) -> None:
      os.makedirs(os.path.dirname(abs_path), exist_ok=True)
      if not os.path.exists(abs_path):
        ext = os.path.splitext(abs_path)[1].lower()
        stub = self._SCAFFOLD_STUBS.get(ext, "")
        with open(abs_path, "w", encoding="utf-8") as f:
          f.write(stub)

    def _materialize_structure_node(self, base_abs: str, node) -> int:
      """Materialize a directory-structure node from System Architect contract."""
      created = 0
      if isinstance(node, dict):
        for key, value in node.items():
          if not isinstance(key, str) or not key.strip():
            continue
          key_norm = key.strip().replace("\\", "/").strip("/")
          target_abs = os.path.join(base_abs, key_norm)
          basename = os.path.basename(key_norm)
          key_is_file = "." in basename and not key_norm.endswith("/")
          if key_is_file and (value is None or isinstance(value, str)):
            if not os.path.exists(target_abs):
              self._touch_file_if_missing(target_abs)
              created += 1
            continue

          child_base = target_abs
          os.makedirs(child_base, exist_ok=True)
          created += self._materialize_structure_node(child_base, value)
        return created

      if isinstance(node, list):
        for item in node:
          if not isinstance(item, str) or not item.strip():
            continue
          rel = item.strip().replace("\\", "/").strip("/")
          target_abs = os.path.join(base_abs, rel)
          basename = os.path.basename(rel)
          is_file = "." in basename and not rel.endswith("/")
          if is_file:
            if not os.path.exists(target_abs):
              self._touch_file_if_missing(target_abs)
              created += 1
          else:
            os.makedirs(target_abs, exist_ok=True)
        return created

      return created

    def _apply_directory_structure_contract_scaffold(self) -> Dict:
      """Create frontend/backend/database trees exactly as declared by System Architect."""
      contract = self._load_directory_structure_contract()
      if not contract.get("ok"):
        return contract

      structure = contract.get("structure", {}) or {}
      total_created = 0
      for top_key, node in structure.items():
        if not isinstance(top_key, str) or not top_key.strip():
          continue
        top_abs = os.path.join(WORKSPACE_DIR, top_key.strip())
        os.makedirs(top_abs, exist_ok=True)
        total_created += self._materialize_structure_node(top_abs, node)

      return {"ok": True, "created_files": total_created}

    def _scaffold_role_from_directory_contract(self, role_key: str) -> None:
      """Materialize only the current role's tree from System Architect directory contract."""
      contract = self._load_directory_structure_contract()
      if not contract.get("ok"):
        raise RuntimeError(
          "CRITICAL: directory structure contract is required before implementation roles can run: "
          f"{contract.get('error', 'unknown error')}"
        )

      role_to_section = {
        "backend_engineer": "backend",
        "frontend_engineer": "frontend",
        "database_architect": "database",
      }
      section = role_to_section.get(role_key)
      if not section:
        return

      structure = contract.get("structure", {}) or {}
      node = structure.get(section, {})
      root_abs = os.path.join(WORKSPACE_DIR, section)
      os.makedirs(root_abs, exist_ok=True)
      self._materialize_structure_node(root_abs, node)

    def _flatten_structure_files(self, node, base_rel: str = "") -> set:
      """Return declared file paths from directory_structure contract node."""
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
            out.update(self._flatten_structure_files(value, child_rel))
      elif isinstance(node, list):
        for item in node:
          if not isinstance(item, str) or not item.strip():
            continue
          rel = item.strip().replace("\\", "/").strip("/")
          basename = os.path.basename(rel)
          is_file = "." in basename and not rel.endswith("/")
          if is_file:
            out.add(f"{base_rel}/{rel}".strip("/") if base_rel else rel)
      return out

    def _verify_directory_structure_alignment(self, role_key: str) -> Dict:
      role_to_section = {
        "backend_engineer": "backend",
        "frontend_engineer": "frontend",
        "database_architect": "database",
      }
      section = role_to_section.get(role_key)
      if not section:
        return {"ok": True, "missing": []}

      contract = self._load_directory_structure_contract()
      if not contract.get("ok"):
        return {
          "ok": False,
          "missing": [f"directory structure verification failed: {contract.get('error', 'unknown error')}"]
        }

      structure = contract.get("structure", {}) or {}
      declared = self._flatten_structure_files(structure.get(section, {}), base_rel=section)
      if not declared:
        return {
          "ok": False,
          "missing": [f"directory structure contract has no declared files for section '{section}'"]
        }

      actual = set(self._list_role_generated_files(role_key))
      missing_files = sorted(declared - actual)
      findings = []
      if missing_files:
        findings.append("missing directory-contract files: " + ", ".join(missing_files[:25]))

      # Extra guard: required database migration files must have real content, not just scaffold stubs.
      CONTENT_REQUIRED = {
        "database/migrations/schema.sql",
        "database/migrations/seed_data.sql",
      }
      for req_path in CONTENT_REQUIRED & declared:
        abs_req = os.path.join(WORKSPACE_DIR, req_path)
        if os.path.exists(abs_req):
          try:
            with open(abs_req, "r", encoding="utf-8", errors="ignore") as _f:
              _content = _f.read().strip()
            if not _content or _content.startswith("-- scaffold placeholder"):
              findings.append(
                f"file exists but contains only scaffold stub (database_architect must write real SQL): {req_path}"
              )
          except Exception:
            pass

      return {"ok": len(findings) == 0, "missing": findings}

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
            if route and " " in route:
              method, raw_path = route.split(" ", 1)
              key = f"{method.upper()} {self._normalize_contract_path(raw_path)}"
              route_map[key] = ep
              continue

            method = str(ep.get("method", "")).strip().upper()
            raw_path = str(ep.get("path", "")).strip()
            if method and raw_path:
              key = f"{method} {self._normalize_contract_path(raw_path)}"
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
        ["system_architect"],
        ["database_architect"],
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

      if "system_architect" not in roles_present:
        raise RuntimeError("CRITICAL: system_architect role is required for contract-first workflow")

      missing = [
        rel for rel in SYSTEM_ARCHITECT_CONTRACTS
        if not os.path.exists(os.path.join(WORKSPACE_DIR, rel))
      ]
      if missing and "system_architect" in roles_present:
        # First layer is allowed to generate these files.
        return
      if missing:
        raise RuntimeError("CRITICAL: missing System Architect contracts: " + ", ".join(missing))

      validation = self._validate_system_architect_contracts(report_issue=True)
      if not validation.get("ok"):
        raise RuntimeError(
          "CRITICAL: System Architect contracts invalid: "
          + str(validation.get("error", "unknown validation failure"))
        )
    
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
      default_root_by_role = {
        "backend_engineer": "backend",
        "frontend_engineer": "frontend",
        "database_architect": "database",
        "qa_engineer": "tests",
        "system_architect": "contracts",
      }
      layout = self.ledger.get("workspace_layout", {}) if isinstance(self.ledger, dict) else {}
      role_map = layout.get("role_output_roots", {}) if isinstance(layout.get("role_output_roots", {}), dict) else {}
      raw_roots = role_map.get(role_key, [])
      if isinstance(raw_roots, str):
        raw_roots = [raw_roots]

      roots = [self._normalize_workspace_rel(r) for r in (raw_roots or []) if self._normalize_workspace_rel(r)]

      # Contract-first override: implementation roles write to contract section roots.
      # This prevents mismatches with legacy director layouts (e.g. apps/backend,
      # db/schemas) when System Architect contracts declare backend/frontend/database.
      contract_role_section = {
        "backend_engineer": "backend",
        "frontend_engineer": "frontend",
        "database_architect": "database",
      }
      section_root = contract_role_section.get(role_key)
      if section_root:
        contract = self._load_directory_structure_contract()
        structure = contract.get("structure", {}) if isinstance(contract, dict) else {}
        if contract.get("ok") and isinstance(structure, dict) and section_root in structure:
          contract_roots = [section_root]
          for r in roots:
            if r and r not in contract_roots:
              contract_roots.append(r)
          return contract_roots

      if role_key == "system_architect":
        # System Architect contracts are single source of truth under contracts/.
        if "contracts" not in roots:
          roots.insert(0, "contracts")
        if "docs/api" not in roots:
          roots.append("docs/api")
        if "docs/system_architecture" not in roots:
          roots.append("docs/system_architecture")
      if roots:
        return roots
      return [default_root_by_role.get(role_key, role_key)]

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
        if role_norm in {"database_architect", "backend_engineer", "frontend_engineer", "qa_engineer"}:
          context["api_contract"] = self._load_contract_context()
          context["contract_required"] = True
        context["system_architect_contracts"] = self._load_system_architect_contract_context(
          require_all=(role_norm != "system_architect")
        )
        
        return context

    def _required_upstream_roles(self, role: str) -> List[str]:
        role_norm = (role or "").strip().lower()
        mapping = {
      "database_architect": ["system_architect"],
        "backend_engineer": ["database_architect", "system_architect"],
        "frontend_engineer": ["system_architect", "backend_engineer"],
            "qa_engineer": ["database_architect", "backend_engineer", "frontend_engineer"],
        }
        return mapping.get(role_norm, [])

    def _enforce_role_prerequisites(self, role: str, current_layer_roles: Optional[List[str]] = None) -> None:
      """Hard gate for contract-first orchestration and upstream dependencies."""
      role_norm = (role or "").strip().lower().replace(" ", "_")
      required = self._required_upstream_roles(role_norm)

      # Only enforce prerequisites for roles that are actually in the plan.
      # If backend_engineer was intentionally excluded (e.g. pure frontend project),
      # it should not block frontend_engineer from starting.
      planned_roles = set()
      try:
        spec = (self.ledger or {}).get("agent_specifications", {}) if isinstance(self.ledger, dict) else {}
        raw_agents = spec.get("required_agents", []) or []
        for a in raw_agents:
          if isinstance(a, str):
            planned_roles.add(a.strip().lower().replace(" ", "_"))
          elif isinstance(a, dict):
            r = a.get("role") or a.get("agent_name") or ""
            planned_roles.add(r.strip().lower().replace(" ", "_"))
      except Exception:
        pass  # If we can't read the ledger, fall through to normal enforcement

      coexecuting_roles = {
        str(r or "").strip().lower().replace(" ", "_")
        for r in (current_layer_roles or [])
      }
      missing_upstream = [
        r for r in required
        if r not in self.completed_workspaces
        and r not in coexecuting_roles
        and (not planned_roles or r in planned_roles)  # skip if not in plan
      ]
      if missing_upstream:
        raise RuntimeError(
          f"CRITICAL: {role_norm} cannot start. Missing completed upstream roles: {', '.join(missing_upstream)}"
        )

      contract_required_roles = {"database_architect", "backend_engineer", "frontend_engineer", "qa_engineer"}
      if role_norm in contract_required_roles:
        missing_contracts = [
          rel for rel in SYSTEM_ARCHITECT_CONTRACTS
          if not os.path.exists(os.path.join(WORKSPACE_DIR, rel))
        ]
        if missing_contracts:
          raise RuntimeError(
            "CRITICAL: System Architect contracts are required before this role can execute: "
            + ", ".join(missing_contracts)
          )
        validation = self._validate_system_architect_contracts(report_issue=True)
        if not validation.get("ok"):
          raise RuntimeError(
            "CRITICAL: System Architect contracts are invalid and cannot be used as source of truth: "
            + str(validation.get("error", "unknown validation failure"))
          )

    def _validate_system_architect_contracts(self, report_issue: bool = False) -> Dict:
      """Validate all System Architect contracts and optionally report failures to system_architect."""
      result = validate_system_architect_contracts(
        workspace_dir=WORKSPACE_DIR,
        backend_rel=BACKEND_API_CONTRACT_REL,
        frontend_rel=FRONTEND_ROUTE_CONTRACT_REL,
        directory_rel=DIRECTORY_STRUCTURE_CONTRACT_REL,
      )
      if result.get("ok"):
        return result

      error_text = str(result.get("error", "unknown validation failure"))
      if report_issue:
        self._report_issue_once(
          component="contracts/system_architect",
          description=(
            "System Architect contracts failed validation: "
            + error_text
            + ". Update backend_api_contract.json, frontend_route_contract.json, and/or directory_structure.json."
          ),
          severity="CRITICAL",
          reported_by="orchestrator_contract_validator",
          assigned_to="system_architect",
          context={"validator_result": result},
        )
        try:
          self.blackboard.post(
            "System",
            "Issues",
            f"System Architect contract validation failed: {error_text}",
          )
        except Exception:
          pass
      return result
    
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

        # NOTE: Route detection verification moved to QA Engineer responsibility
        # QA Engineer will run backend/frontend and manually verify routes/pages
        # This removes architectural mismatch between static analysis and Express routing
        # contract_check = self._verify_contract_alignment(role_key, workspace)
        # if not contract_check["ok"]:
        #   missing.extend(contract_check.get("missing", []))

        dir_check = self._verify_directory_structure_alignment(role_key)
        if not dir_check.get("ok"):
          missing.extend(dir_check.get("missing", []))

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
        timeout_value = None
        if timeout_seconds is not None and int(timeout_seconds) > 0:
          timeout_value = max(5, int(timeout_seconds))
        elif long_running_ok:
          # Keep a bounded probe window for dev/start scripts so smoke checks do not block forever.
          timeout_value = 25
        completed = subprocess.run(
          cmd,
          cwd=workspace,
          capture_output=True,
          text=True,
          timeout=timeout_value,
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
        route_test_like = None
        for candidate in ["test:routes", "test:api"]:
          if candidate in scripts:
            route_test_like = candidate
            break

        if not route_test_like:
          return {
            "ok": False,
            "error": "runtime smoke check: backend must define route test script (test:routes or test:api)",
            "checks": checks,
          }

        test_out = self._run_npm_script(
          workspace,
          route_test_like,
          timeout_seconds=RUNTIME_SMOKE_TIMEOUT_SECONDS,
          long_running_ok=False,
        )
        checks.append({"script": route_test_like, **test_out})
        if not test_out.get("ok"):
          return {
            "ok": False,
            "error": test_out.get("message", "backend route tests failed"),
            "checks": checks,
            "output": test_out.get("output", ""),
          }

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

    def _report_issue_once(
      self,
      component: str,
      description: str,
      severity: str,
      reported_by: str,
      assigned_to: str,
      context: Optional[Dict] = None,
    ) -> None:
      tracker = get_issues_tracker()
      open_for_assignee = tracker.get_open_issues(assigned_to=assigned_to)
      norm_component = (component or "").strip().lower()
      norm_desc = (description or "").strip().lower()
      for issue in open_for_assignee:
        if not isinstance(issue, dict):
          continue
        if str(issue.get("component", "")).strip().lower() != norm_component:
          continue
        existing = str(issue.get("description", "")).strip().lower()
        if existing == norm_desc or norm_desc[:140] in existing:
          return

      tracker.report_issue(
        component=component,
        description=description,
        severity=severity,
        reported_by=reported_by,
        assigned_to=assigned_to,
        context=context or {},
      )

    def _notify_runtime_failure(self, failing_role: str, runtime_error: str, runtime_output: str = "") -> None:
      if failing_role not in {"backend_engineer", "frontend_engineer"}:
        return

      peer_role = "frontend_engineer" if failing_role == "backend_engineer" else "backend_engineer"
      output_tail = (runtime_output or "")[-1200:]
      base_context = {
        "failing_role": failing_role,
        "peer_role": peer_role,
        "runtime_error": runtime_error,
        "runtime_output_tail": output_tail,
      }

      self._report_issue_once(
        component=f"runtime/{failing_role}",
        description=(
          f"Runtime smoke check failed for {failing_role}: {runtime_error}. "
          "Fix and rerun verification before completion."
        ),
        severity="CRITICAL",
        reported_by="orchestrator_runtime_check",
        assigned_to=failing_role,
        context=base_context,
      )

      self._report_issue_once(
        component=f"integration/{failing_role}",
        description=(
          f"Dependency runtime failure in {failing_role}: {runtime_error}. "
          f"{peer_role} must monitor and re-validate integration once the fix lands."
        ),
        severity="HIGH",
        reported_by="orchestrator_runtime_check",
        assigned_to=peer_role,
        context=base_context,
      )

      try:
        self.blackboard.post(
          "System",
          "Issues",
          (
            f"Runtime check failed for {failing_role}. "
            f"Notified {failing_role} (fix owner) and {peer_role} (integration watcher)."
          ),
        )
      except Exception:
        pass

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
      """Load contract routes as {'METHOD /path': meta} map from backend API contract."""
      contract_path = os.path.join(WORKSPACE_DIR, BACKEND_API_CONTRACT_REL)
      if not os.path.exists(contract_path):
        legacy = os.path.join(WORKSPACE_DIR, "contracts", "api_contract.json")
        contract_path = legacy if os.path.exists(legacy) else contract_path
      data = self._read_json_file(contract_path)
      if not isinstance(data, dict):
        return {"ok": False, "routes": {}, "error": f"{BACKEND_API_CONTRACT_REL} missing or invalid JSON"}

      route_map = self._extract_contract_route_map(data)
      if not route_map:
        return {
          "ok": False,
          "routes": {},
          "error": f"{BACKEND_API_CONTRACT_REL} has no usable routes (expected endpoints[] or paths{{}})"
        }
      return {"ok": True, "routes": route_map}

    def _auto_heal_empty_contract(self) -> bool:
      """System Architect contract must be explicit; no auto-generated fallbacks."""
      return False

    def _collect_backend_routes(self, workspace: str) -> Dict:
        """Collect effective backend routes as {'METHOD /path'} from app mounts + route files."""
        app_candidates = [
          os.path.join(workspace, "app.js"),
          os.path.join(workspace, "server.js"),
          os.path.join(workspace, "index.js"),
        ]
        app_entry = next((p for p in app_candidates if os.path.exists(p)), "")
        app_src = ""
        if app_entry:
          try:
            with open(app_entry, "r", encoding="utf-8", errors="ignore") as f:
              app_src = f.read()
          except Exception as e:
            return {"ok": False, "routes": set(), "error": f"failed reading backend entry file: {str(e)}"}

        var_to_route_file = {}
        require_re = re.compile(r"(?:const|let|var)\s+(\w+)\s*=\s*require\(['\"](\.[^'\"]+)['\"]\)")
        for m in require_re.finditer(app_src):
            var_to_route_file[m.group(1)] = m.group(2)

        mount_re = re.compile(r"app\.use\(\s*['\"]([^'\"]+)['\"]\s*,\s*(\w+)\s*\)")
        mount_inline_require_re = re.compile(
          r"app\.use\(\s*['\"]([^'\"]+)['\"]\s*,\s*require\(\s*['\"](\.[^'\"]+)['\"]\s*\)\s*\)"
        )
        mount_inline_controller_re = re.compile(
          r"app\.use\(\s*['\"]([^'\"]+)['\"]\s*,\s*require\(\s*['\"]\./controllers/[^'\"]+['\"]\s*\)"
        )
        mount_no_base_re = re.compile(r"app\.use\(\s*(\w+)\s*\)")
        mount_no_base_inline_require_re = re.compile(
          r"app\.use\(\s*require\(\s*['\"](\.[^'\"]+)['\"]\s*\)\s*\)"
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

        # Fallback: if mounts were not detected, scan common routes folders.
        if not mounted:
          candidate_dirs = [
            os.path.join(workspace, "routes"),
            os.path.join(workspace, "api", "routes"),
          ]
          for routes_dir in candidate_dirs:
            if not os.path.isdir(routes_dir):
              continue
            for root, _, files in os.walk(routes_dir):
              for name in files:
                if not name.endswith(".js"):
                  continue
                abs_file = os.path.join(root, name)
                rel_no_ext = os.path.splitext(os.path.relpath(abs_file, workspace))[0]
                mounted.append(("", f"./{rel_no_ext.replace(os.sep, '/')}"))

        routes = set()
        app_route_decl_re = re.compile(r"app\.(get|post|put|patch|delete)\(\s*['\"]([^'\"]+)['\"]")
        for rm in app_route_decl_re.finditer(app_src):
          method = rm.group(1).upper()
          full_path = self._normalize_api_path(rm.group(2))
          routes.add(f"{method} {full_path}")

        route_decl_re = re.compile(r"router\.(get|post|put|patch|delete)\(\s*['\"]([^'\"]+)['\"]")
        for mount_base, route_rel in mounted:
          if str(route_rel).startswith("."):
            abs_route_file = os.path.normpath(os.path.join(workspace, route_rel))
          else:
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
            full_path = self._normalize_api_path(f"{mount_base}/{sub_path.lstrip('/')}" )
            routes.add(f"{method} {full_path}")

        return {"ok": True, "routes": routes, "methodless_paths": methodless_paths}

    def _collect_frontend_api_calls(self, workspace: str) -> Dict:
        """Collect frontend API calls from api util or source files as {'METHOD /path'} set."""
        api_candidates = [
          os.path.join(workspace, "src", "utils", "api.js"),
          os.path.join(workspace, "src", "services", "api.js"),
          os.path.join(workspace, "src", "api.js"),
          os.path.join(workspace, "api.js"),
        ]
        source_files = [p for p in api_candidates if os.path.exists(p)]
        if not source_files:
          for root, dirs, files in os.walk(workspace):
            dirs[:] = [d for d in dirs if d not in {"node_modules", "dist", "build", ".next", ".git"}]
            for file_name in files:
              if file_name.endswith((".js", ".jsx", ".ts", ".tsx")):
                source_files.append(os.path.join(root, file_name))
        if not source_files:
          return {"ok": False, "routes": set(), "error": "frontend source files not found"}

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

        for src_file in source_files:
          try:
            with open(src_file, "r", encoding="utf-8", errors="ignore") as f:
              src = f.read()
          except Exception:
            continue

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

    def _normalize_frontend_route_path(self, path: str) -> str:
      p = (str(path or "").strip() or "/").replace("//", "/")
      if not p.startswith("/"):
        p = "/" + p
      if len(p) > 1:
        p = p.rstrip("/")
      return p

    def _extract_frontend_contract_routes(self, payload: Dict) -> set:
      routes = set()
      if not isinstance(payload, dict):
        return routes

      def _maybe_add(value):
        if isinstance(value, str):
          t = value.strip()
          if t.startswith("/"):
            routes.add(self._normalize_frontend_route_path(t))
        elif isinstance(value, dict):
          for key in ["path", "route", "url", "href"]:
            v = value.get(key)
            if isinstance(v, str) and v.strip().startswith("/"):
              routes.add(self._normalize_frontend_route_path(v.strip()))

      for key in ["routes", "pages", "navigation", "menu"]:
        section = payload.get(key)
        if isinstance(section, list):
          for item in section:
            _maybe_add(item)

      return routes

    def _collect_frontend_routes(self, workspace: str) -> Dict:
      routes = set()
      src_root = os.path.join(workspace, "src")
      root_pages_dir = os.path.join(workspace, "pages")
      if not os.path.isdir(src_root) and not os.path.isdir(root_pages_dir):
        return {"ok": False, "routes": set(), "error": "frontend source directory not found (expected src/ or pages/)"}

      # Next.js pages convention.
      pages_dir = os.path.join(src_root, "pages")
      if not os.path.isdir(pages_dir):
        pages_dir = root_pages_dir
      if os.path.isdir(pages_dir):
        for name in os.listdir(pages_dir):
          if not name.endswith((".js", ".jsx", ".ts", ".tsx")):
            continue
          stem = os.path.splitext(name)[0]
          if stem.startswith("_"):
            continue
          if stem.lower() == "index":
            routes.add("/")
          else:
            routes.add(self._normalize_frontend_route_path(f"/{stem}"))

      path_attr_re = re.compile(r"\bpath\s*=\s*['\"]([^'\"]+)['\"]")
      href_attr_re = re.compile(r"\bhref\s*=\s*['\"](/[^'\"]*)['\"]")

      scan_roots = []
      if os.path.isdir(src_root):
        scan_roots.append(src_root)
      if os.path.isdir(root_pages_dir):
        scan_roots.append(root_pages_dir)

      for scan_root in scan_roots:
        for root, dirs, files in os.walk(scan_root):
          dirs[:] = [d for d in dirs if d not in {"node_modules", "dist", "build", ".next"}]
          for file_name in files:
            if not file_name.endswith((".js", ".jsx", ".ts", ".tsx")):
              continue
            abs_path = os.path.join(root, file_name)
            try:
              with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                src = f.read()
            except Exception:
              continue

            for m in path_attr_re.finditer(src):
              routes.add(self._normalize_frontend_route_path(m.group(1)))
            for m in href_attr_re.finditer(src):
              route = m.group(1)
              if route.startswith("/#") or route.startswith("#"):
                continue
              routes.add(self._normalize_frontend_route_path(route))

      return {"ok": True, "routes": routes}

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
        """DEPRECATED: Route detection moved to QA Engineer.
        
        This function is no longer called during orchestration.
        
        QA Engineer is now responsible for:
        1. Starting backend and frontend servers
        2. Manually testing routes and pages by navigating/calling them
        3. Identifying and reporting mismatches with evidence
        4. Waking up agents if issues found using service bus
        
        Reason: Static regex analysis cannot understand:
        - Express routing patterns (app.use() with router mounting)
        - Framework abstractions (Next.js dynamic routes, etc.)
        - The semantic relationship between route definitions and mounted paths
        - Runtime behavior that depends on middleware ordering
        
        QA Engineer's runtime testing is the ground truth.
        """
        # Disabled - all contract verification delegated to QA Engineer
        return {"ok": True, "missing": []}

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
        # Always permit the required database migration files so retries can write real content.
        if base == "database":
          allowed_new.update({
            f"{base}/migrations/schema.sql",
            f"{base}/migrations/seed_data.sql",
          })

      tr.retry_allowed_new_paths = allowed_new
      tr.max_writes_per_file = min(int(getattr(tr, "max_writes_per_file", 6) or 6), 2)
    
    def _execute_agent(self, agent_spec: Dict, context: Dict, parallel_agents: List[str] = None, layer_blackboard = None, layer_sleep: Optional[LayerSleepCoordinator] = None, layer_index: int = None, current_layer_roles: Optional[List[str]] = None) -> str:
        """Execute an agent using GeneralAgent framework"""
        role = agent_spec.get("role", "unknown")
        role_key = role.lower().replace(" ", "_")
        print(f"[DEBUG] _execute_agent called for role: {role}")
        workspace = self._get_agent_workspace(role)

        if role_key in {"backend_engineer", "frontend_engineer", "database_architect"}:
          self._scaffold_role_from_directory_contract(role_key)

        # Hard-gate semantic prerequisites (contract-first + upstream readiness)
        self._enforce_role_prerequisites(role, current_layer_roles=current_layer_roles)
        
        if parallel_agents is None:
            parallel_agents = []
        
        # Initialize agents with blackboard access
        set_blackboard(self.blackboard)
        
        # SPECIAL HANDLING FOR QA AGENT: Limit context to prevent token overflow
        # QA agent gets file discovery instructions but not all files listed upfront
        if "qa" in role.lower() or "test" in role.lower():
            upstream_roles = ["database_architect", "backend_engineer", "frontend_engineer"]
            upstream_agents = {
              r: os.path.join(WORKSPACE_DIR, self._get_role_output_roots(r)[0])
                for r in upstream_roles
            }
            context_for_qa = {
                "project_name": context.get("project_name", ""),
                "requirements": context.get("requirements", []),
                "tech_stack": context.get("tech_stack", {}),
                "previous_outputs": context.get("previous_outputs", {}),
                "required_upstream_roles": context.get("required_upstream_roles", []),
                "upstream_agents": upstream_agents,
              "system_architect_contracts": context.get("system_architect_contracts", {}),
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
          if role_key in {"backend_engineer", "frontend_engineer", "database_architect"}:
            owned_root = output_roots[0] if output_roots else role_key
            agent.tools_registry.preferred_output_roots = [owned_root]
            agent.tools_registry.primary_output_root = owned_root
            agent.tools_registry.shared_write_roots = []
            agent.tools_registry.edit_only_mode = False
            agent.tools_registry.allow_delete_operations = False
          else:
            agent.tools_registry.preferred_output_roots = list(output_roots)
            agent.tools_registry.primary_output_root = output_roots[0] if output_roots else ""
            agent.tools_registry.edit_only_mode = False
            agent.tools_registry.allow_delete_operations = True

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
            if role_norm == "system_architect":
              role_boundary_text = """

ROLE BOUNDARY (MANDATORY):
- You are the SYSTEM ARCHITECT AGENT.
- Your ONLY responsibility is to define COMPLETE, PRECISE, and MACHINE-ENFORCEABLE architecture contracts.
- You DO NOT write implementation code.
- You ARE responsible for ensuring all FOUNDATIONAL files are declared in directory_structure.json.

⚠️  CRITICAL ARCHITECTURAL RESPONSIBILITY:
  Your contracts MUST include entry point/startup files for each tech stack:
  
  FOR EXPRESS.JS (Node.js) BACKENDS:
    → Include backend/app.js in directory_structure_contract (owned by backend_engineer)
    → app.js MUST mount all routes with express.use()
    → Backend engineer depends on this existing and being correctly wired
  
  FOR NEXT.JS (React) FRONTENDS:
    → pages/ directory structure MUST be complete in directory_structure_contract
    → All route files MUST be listed (pages/*.jsx, pages/api/*.js)
  
  FOR OTHER FRAMEWORKS:
    → Document the entry point clearly (e.g., main.py, index.js, etc.)
    → Include in directory_structure_contract

OUTPUT FORMAT (STRICT):
- You MUST output ONLY valid JSON files.
- NO explanations, NO markdown, NO prose.
- Each contract MUST strictly follow the schemas defined below.
- Any deviation = INVALID OUTPUT.

MANDATORY DELIVERABLES (ALL REQUIRED):
1. contracts/backend_api_contract.json
2. contracts/frontend_route_contract.json
3. contracts/directory_structure.json

═══════════════════════════════════════
GLOBAL RULES (NON-NEGOTIABLE)
═══════════════════════════════════════

- NO AMBIGUITY: no "etc", "optional", "additional fields"
- NO GUESSING: if requirements unclear → define explicitly or mark as required input
- NO DUPLICATION: each entity must have a unique ID
- ALL REFERENCES MUST USE IDs (NOT RAW STRINGS)

═══════════════════════════════════════
BACKEND API CONTRACT (STRICT SCHEMA)
═══════════════════════════════════════

{
  "endpoints": [
    {
      "id": "unique_endpoint_id",
      "method": "GET|POST|PUT|DELETE",
      "path": "/api/...",
      "path_params": [{ "name": "...", "type": "string|number" }],
      "query_params": [{ "name": "...", "type": "...", "required": true }],
      "request_body": { ... STRICT JSON SCHEMA ... },
      "responses": {
        "200": { ... STRICT JSON SCHEMA ... },
        "400": { ... },
        "404": { ... },
        "500": { ... }
      }
    }
  ]
}

RULES:
- Every endpoint MUST have a unique "id"
- Paths MUST be canonical (no variations allowed)
- ALL fields MUST have explicit types

═══════════════════════════════════════
FRONTEND ROUTE CONTRACT (STRICT SCHEMA)
═══════════════════════════════════════

{
  "routes": [
    {
      "id": "unique_route_id",
      "path": "/...",
      "params": [{ "name": "...", "type": "string|number" }],
      "uses_endpoints": ["endpoint_id_1", "endpoint_id_2"],
      "auth_required": true|false,
      "description": "STRICT: describe responsibilities"
    }
  ]
}

RULES:
- MUST reference backend endpoints by ID (NOT path strings)
- EVERY route MUST declare backend dependencies
- EVERY route MUST be reachable (no orphan routes)

═══════════════════════════════════════
DIRECTORY STRUCTURE CONTRACT
═══════════════════════════════════════

{
  "structure": [
    {
      "path": "backend/routes/users.js",
      "type": "file",
      "owned_by": "backend_engineer",
      "purpose": "maps to endpoint_ids: [...]"
    },
    {
      "path": "frontend/pages/Books.jsx",
      "type": "file",
      "owned_by": "frontend_engineer",
      "purpose": "maps to route_ids: [...]"
    }
  ]
}

RULES:
- EVERY endpoint_id MUST map to at least one backend file
- EVERY route_id MUST map to at least one frontend file
- MUST declare at least one file under EACH: backend/, frontend/, database/
- DATABASE FILES ARE MANDATORY: include concrete database files (not empty placeholders), including at minimum:
  - database/migrations/schema.sql
  - database/migrations/seed_data.sql
  - database/README.md
- Database files in directory_structure.json MUST be owned_by: "database_architect"
- ENTRY POINT FILES ARE MANDATORY: Every backend/frontend MUST have a working entry point:
  - Node.js backends: backend/app.js (Express app with route mounting)
  - Next.js frontends: frontend/pages/*.jsx with proper routing
  - Entry points owned_by appropriate implementation agent, but DEFINED by you
- NO unused files allowed
- NO missing mappings allowed

═══════════════════════════════════════
CONSISTENCY REQUIREMENTS (CRITICAL)
═══════════════════════════════════════

You MUST verify:

1. Every frontend route → references valid endpoint IDs
2. Every endpoint → used by at least one route OR explicitly marked unused
3. Every file → maps to valid route_id or endpoint_id
4. No orphan entities (routes/endpoints/files)

═══════════════════════════════════════
FORBIDDEN ACTIONS
═══════════════════════════════════════

- DO NOT invent endpoints outside this contract
- DO NOT leave unspecified fields
- DO NOT output partial contracts
- DO NOT produce human-readable explanations

═══════════════════════════════════════
SUCCESS CRITERIA
═══════════════════════════════════════

- All contracts are internally consistent
- All references resolve correctly
- Implementation agents can proceed WITHOUT ANY assumptions
- Contracts are fully machine-parseable and enforceable

If ANY assumption would be required → CONTRACT IS INVALID
"""
            elif role_norm == "database_architect":
              role_boundary_text = """

ROLE BOUNDARY (MANDATORY):
- You must strictly follow all System Architect contracts.
- You can create and edit files inside your owned database directory.
- Do not modify files outside your ownership boundaries.

MANDATORY SELF-CHECK BEFORE READY TOKEN:
- Confirm every edited file exists in contracts/directory_structure.json.
- Confirm schema/security assumptions align with contracts/backend_api_contract.json.
"""
            elif role_norm == "backend_engineer":
              role_boundary_text = """

ROLE BOUNDARY (MANDATORY):
- Treat contracts/backend_api_contract.json as authoritative API source of truth.
- Implement endpoints, request/response schemas, field names, and status codes EXACTLY as contract defines.
- You MUST NOT invent new routes or payload fields unless contract is updated first.
- You can create and edit files inside your owned backend directory.
- Do not modify files outside your ownership boundaries.
- Implement production-ready controllers/services and route wiring in your workspace.
- Avoid conflicting duplicate route/module names; ensure imports resolve to real local files.

MANDATORY SELF-CHECK BEFORE READY TOKEN:
- Build a route matrix of contract route -> implemented route.
- Verify HTTP method and full path EXACT match for every contract endpoint.
- Verify path param names EXACT match (e.g., :order_id must not become :id).
- Verify no extra backend API routes exist outside contract.
- Verify all edited files are listed in contracts/directory_structure.json.
"""
            elif role_norm == "frontend_engineer":
              role_boundary_text = """

ROLE BOUNDARY (MANDATORY):
- Treat contracts/backend_api_contract.json and contracts/frontend_route_contract.json as authoritative sources.
- Consume API paths, params, payloads, response fields, and error shapes EXACTLY as contract defines.
- You MUST NOT invent frontend-only API fields/routes/pages.
- You can create and edit files inside your owned frontend directory.
- Do not modify files outside your ownership boundaries.
- If API mismatch is found, request contract correction instead of guessing.

MANDATORY SELF-CHECK BEFORE READY TOKEN:
- Build a call matrix of frontend API call -> contract endpoint.
- Verify each API path + method in frontend exists in contracts/backend_api_contract.json.
- Verify path param names EXACT match contract names.
- Verify frontend does not call non-contract endpoints.
- Verify all edited pages/routes match contracts/frontend_route_contract.json.
- Verify all edited files are listed in contracts/directory_structure.json.
"""
            elif role_norm == "qa_engineer":
              role_boundary_text = """

ROLE BOUNDARY (MANDATORY):
- Your primary mission is verification, not feature implementation.
- Use System Architect contracts as compulsory source of truth every run.
- Validate EACH endpoint/page/route against contracts and runtime behavior.
- You may create verification scripts/tests and an issues list.

MANDATORY CHECKLIST:
- Verify backend endpoints from contracts/backend_api_contract.json exist and behave as specified.
- Verify frontend routes/pages from contracts/frontend_route_contract.json exist and load as specified.
- Verify generated files follow contracts/directory_structure.json.
- Report every mismatch as concrete issue evidence (path, expected, actual).
"""

            cross_layer_repair_text = """

CROSS-LAYER WAKE-UP POLICY (MANDATORY):
- If blocked by another agent (including previous layers), call report_issue with concrete evidence and exact missing paths.
- For System Architect/scaffold/contract blockers, set assigned_to="system_architect".
- The orchestrator runs ISSUE WAKE cycles and can wake previously completed layers to patch blockers.
- After wake/fix, re-read changed files and continue; do not stall or guess around blockers.
"""
            
            task_description = f"""
Project: {context.get('project_name', 'Project')}

Your task as {role}:
{agent_spec.get('instructions', 'Implement your role responsibilities')}{parallel_info}{layer_onboarding_text}{role_boundary_text}{cross_layer_repair_text}

Requirements:
{chr(10).join(f"- {req}" for req in context.get('requirements', []))}

Technology Stack:
- Backend: {', '.join(context.get('tech_stack', {}).get('backend_frameworks', []))}
- Frontend: {', '.join(context.get('tech_stack', {}).get('frontend_frameworks', []))}
- Databases: {', '.join(context.get('tech_stack', {}).get('databases', []))}

CRITICAL WORKSPACE INFO:
- You must respect ownership boundaries and role-specific file permissions.
- Preferred production output roots for your role:
{output_roots_text}
- If your allowed root already equals your primary output root, write paths relative to it.
  Example: use "controllers/user.js" (not "backend/controllers/user.js") when rooted at backend/.
- Write files to production paths (e.g., backend/, frontend/, database/, infra/, tests/), not role-named folders.
- Respect layer onboarding contracts for target folders/interfaces.
- Backend/Frontend/Database roles may create/edit files inside owned roots; ownership boundaries still apply.

COMPLETION CONTRACT (MANDATORY):
- Do NOT finish after planning only.
- Produce real deliverable code in scaffolded files.
- You may create/edit files within owned roots; do not write outside ownership boundaries.
- Update dependency manifest (package.json/requirements.txt/pyproject.toml) or README.md ONLY when those files are declared for your role in contracts/directory_structure.json and exist in scaffold.
- If verification expects missing scaffold files, call report_issue with assigned_to="system_architect" and include exact missing paths.
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

            architect_ctx = context.get("system_architect_contracts") if isinstance(context, dict) else None
            if architect_ctx and isinstance(architect_ctx, dict):
                task_description += "\n\nSYSTEM ARCHITECT CONTRACTS (COMPULSORY CONTEXT):\n"
                for key in ["backend_api_contract", "frontend_route_contract", "directory_structure_contract"]:
                    payload = architect_ctx.get(key)
                    if not isinstance(payload, dict):
                        continue
                    task_description += f"""

- Contract: {payload.get('path', key)}
  SHA256: {payload.get('checksum_sha256', '')}
  REQUIRED: follow this EXACTLY with zero drift.
{payload.get('content', '')}
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

          attempt = 0
          while True:
            attempt += 1
            if max_attempts > 0 and attempt > max_attempts:
              break
            attempt_label = f"{attempt}/{max_attempts}" if max_attempts > 0 else f"{attempt}/∞"
            can_retry = (max_attempts <= 0) or (attempt < max_attempts)
            print(f"[DEBUG] About to call agent.execute() for {role} (attempt {attempt_label})")

            if attempt > 1:
              retry_snapshot = self._build_retry_workspace_snapshot(role, workspace)
              task_description += f"""

    RETRY CONTEXT (attempt {attempt_label}):
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

            attempt_context = dict(context or {})
            attempt_context["retry_context"] = {
              "attempt": attempt,
              "max_attempts": max_attempts,
              "failure_reason": last_failure_reason,
              "verification_hints": list(last_missing_hints or []),
              "allowed_new_paths": sorted(last_allowed_new_paths) if last_allowed_new_paths else [],
            }

            api_call_attempt = 0
            while True:
              self._wait_if_globally_paused()
              try:
                while True:
                  result = agent.execute(
                    task_description=task_description,
                    context=attempt_context
                  )
                  if (result or "").strip() != "[SLEEP_REQUESTED]":
                    break

                  if layer_sleep is None:
                    raise RuntimeError("Sleep requested but no layer sleep coordinator is configured")

                  print(f"⏸️ [{role}] entered sleep mode waiting for a wake signal...")
                  wake_payload = layer_sleep.wait_until_woken(
                    role,
                    timeout_seconds=max(5, int(SLEEP_RECHECK_SECONDS)),
                  )
                  if not wake_payload:
                    print(
                      f"⏰ [{role}] periodic sleep recheck fired after "
                      f"{max(5, int(SLEEP_RECHECK_SECONDS))}s without wake signal"
                    )
                    wake = {
                      "woken_by": "system_periodic_recheck",
                      "resolution": (
                        "No peer wake signal yet. Re-check blocking issues now; "
                        "if still blocked, call sleep_agent() again."
                      ),
                    }
                  else:
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
            write_ops = 0
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
                if max_attempts > 0 and attempt == max_attempts:
                  print(f"⚠️ [{role}] forcing external verification on final attempt after readiness-loop exhaustion")
                  has_ready_token = True
              else:
                last_failure_reason = "agent did not output [READY_FOR_VERIFICATION]"

            if has_ready_token and role_key == "system_architect" and is_fix_mode and write_ops == 0:
              has_ready_token = False
              last_failure_reason = "system_architect wake-up run emitted readiness without modifying contracts"

            if not has_ready_token:
              if can_retry:
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
              if can_retry:
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
              if can_retry:
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
              if can_retry:
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
              self._notify_runtime_failure(role_key, runtime_err, runtime_out)
              last_failure_reason = f"runtime smoke check failed: {runtime_err}"
              last_missing_hints = [runtime_err, runtime_out]
              last_allowed_new_paths = set()
              print(f"⚠️ [{role}] runtime smoke failed, retrying remediation")
              if can_retry:
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
            if can_retry:
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
        max_wait_seconds = int(LAYER_MAX_WAIT_SECONDS)
        if max_wait_seconds <= 0:
          for thread in threads:
            thread.join()
        else:
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
          # Contract-first hardening: after system_architect layer, ensure contract has usable routes.
          if layer_index >= 1:
            self._auto_heal_empty_contract()
          self.execute_layer(layer_index, agents_in_layer)

          layer_roles = {
            str(a.get("role", "")).strip().lower().replace(" ", "_")
            for a in (agents_in_layer or []) if isinstance(a, dict)
          }
          if "system_architect" in layer_roles:
            contract_validation = self._validate_system_architect_contracts(report_issue=True)
            if not contract_validation.get("ok"):
              raise RuntimeError(
                "CRITICAL: System Architect contract validation failed: "
                + str(contract_validation.get("error", "unknown validation failure"))
              )
            scaffold = self._apply_directory_structure_contract_scaffold()
            if not scaffold.get("ok"):
              raise RuntimeError(
                "CRITICAL: failed to materialize System Architect directory structure: "
                + str(scaffold.get("error", "unknown error"))
              )
            print(
              "🧱 Applied System Architect directory scaffold "
              f"({scaffold.get('created_files', 0)} files materialized)"
            )
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