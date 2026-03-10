"""
Healer Agent - Code Quality Review and Issue Detection
Scans generated code files, identifies issues, and coordinates fixes.
Integrates with Director AI to restart agents for remediation.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ==========================================
# CONFIGURATION
# ==========================================
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")
GENERATED_CODE_DIR = Path("./generated_code")

# Initialize Azure OpenAI
client = AzureOpenAI(
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_key=AZURE_OPENAI_KEY,
    api_version=AZURE_OPENAI_API_VERSION,
)

# ==========================================
# DATA MODELS
# ==========================================
class IssueSeverity(str, Enum):
    """Issue severity levels"""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IssueCategory(str, Enum):
    """Issue categories"""
    SECURITY = "security"
    LOGIC = "logic"
    BUG = "bug"
    STYLE = "style"
    PERFORMANCE = "performance"
    MISSING = "missing"
    TYPE_ERROR = "type_error"


@dataclass
class CodeIssue:
    """Represents a single code issue found during review"""
    file_path: str
    line_start: int
    line_end: int
    severity: IssueSeverity
    category: IssueCategory
    description: str
    code_snippet: str
    suggestion: Optional[str] = None
    agent_role: Optional[str] = None  # Which agent should fix this

    def to_dict(self) -> Dict:
        data = asdict(self)
        data['severity'] = self.severity.value
        data['category'] = self.category.value
        return data


@dataclass
class HealerResult:
    """Result of the healer agent's code review"""
    project_id: str
    total_files_reviewed: int
    total_issues_found: int
    issues_by_severity: Dict[str, int]
    issues_by_category: Dict[str, int]
    issues: List[CodeIssue]
    timestamp: str
    execution_time_seconds: float

    def to_dict(self) -> Dict:
        return {
            "project_id": self.project_id,
            "total_files_reviewed": self.total_files_reviewed,
            "total_issues_found": self.total_issues_found,
            "issues_by_severity": self.issues_by_severity,
            "issues_by_category": self.issues_by_category,
            "issues": [issue.to_dict() for issue in self.issues],
            "timestamp": self.timestamp,
            "execution_time_seconds": self.execution_time_seconds,
        }


# ==========================================
# REVIEW SYSTEM PROMPT
# ==========================================
REVIEW_SYSTEM_PROMPT = """You are an expert code reviewer and quality assurance specialist.
Analyze the provided code file and identify ALL issues including:
- Security vulnerabilities (SQL injection, XSS, auth failures, etc.)
- Logic errors and incorrect algorithms
- Bugs and runtime errors
- Type errors and incorrect type hints
- Style and best practice violations
- Missing error handling
- Performance issues
- Missing required functionality

For each issue, respond with ONLY a valid JSON array. Do not include markdown, explanations, or text outside the JSON.
Each element must have exactly these keys:
  {
    "line_start": <int>,
    "line_end": <int>,
    "severity": "LOW|MEDIUM|HIGH|CRITICAL",
    "category": "security|logic|bug|style|performance|missing|type_error",
    "description": "<clear explanation of the issue>",
    "code_snippet": "<the problematic code>",
    "suggestion": "<how to fix it>"
  }

severity levels:
- LOW: Style issues, minor improvements
- MEDIUM: Potential bugs, missing error handling
- HIGH: Security vulnerabilities, logic errors, data corruption risks
- CRITICAL: Complete failure, security breach, data loss

If no issues found, return an empty JSON array: []
"""


# ==========================================
# HEALER AGENT IMPLEMENTATION
# ==========================================
class HealerAgent:
    """
    Scans generated code files and identifies quality issues.
    Coordinates with Director to restart agents for fixes.
    """

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.issues: List[CodeIssue] = []
        self.files_reviewed = 0

    def _get_generated_files(self) -> List[tuple[str, str]]:
        """
        Recursively get all generated code files.
        Returns: List of (relative_path, full_content) tuples
        """
        files = []
        
        if not GENERATED_CODE_DIR.exists():
            logger.warning(f"Generated code directory not found: {GENERATED_CODE_DIR}")
            return files

        # Skip certain directories and files
        skip_dirs = {"__pycache__", ".pytest_cache", "node_modules", ".git"}
        skip_extensions = {".pyc", ".pyo", ".class", ".o", ".so"}

        for file_path in GENERATED_CODE_DIR.rglob("*"):
            if not file_path.is_file():
                continue

            # Skip certain paths
            if any(skip_dir in file_path.parts for skip_dir in skip_dirs):
                continue
            if file_path.suffix in skip_extensions:
                continue

            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                relative_path = str(file_path.relative_to(GENERATED_CODE_DIR))
                files.append((relative_path, content))
            except Exception as e:
                logger.warning(f"Could not read file {file_path}: {e}")
                continue

        return files

    def _infer_agent_role(self, file_path: str, category: IssueCategory) -> str:
        """Infer which agent role should handle this issue"""
        file_lower = file_path.lower()
        category_lower = category.value.lower()

        # Map file paths to agent roles
        if any(x in file_lower for x in ["backend", "server", "api", "controller", "route"]):
            return "backend_engineer"
        elif any(x in file_lower for x in ["frontend", "ui", "component", "page", "tsx", "jsx"]):
            return "frontend_engineer"
        elif any(x in file_lower for x in ["database", "schema", "migration", "sql"]):
            return "database_architect"
        elif any(x in file_lower for x in ["docker", "compose", "ci", "cd", "deploy", "infra", "terraform"]):
            return "devops_engineer"
        elif any(x in file_lower for x in ["test", "spec"]):
            return "qa_engineer"
        elif any(x in file_lower for x in ["security", "auth", "crypto"]):
            return "security_engineer"
        elif any(x in file_lower for x in ["ml", "ai", "model", "pipeline"]):
            return "ml_engineer"

        # Map category to agent
        if category == IssueCategory.SECURITY:
            return "security_engineer"
        elif category == IssueCategory.LOGIC or category == IssueCategory.BUG:
            return "backend_engineer"
        elif category == IssueCategory.TYPE_ERROR:
            return "backend_engineer"
        elif category == IssueCategory.PERFORMANCE:
            return "devops_engineer"

        return "backend_engineer"  # Default

    def _review_file(self, file_path: str, content: str) -> List[CodeIssue]:
        """
        Send file to GPT-4o for code review.
        Returns: List of CodeIssue objects
        """
        # Skip very large files
        if len(content) > 50000:
            logger.warning(f"File too large, truncating: {file_path}")
            content = content[:50000] + "\n... [truncated] ..."

        # Skip binary-like content
        if "\x00" in content:
            logger.debug(f"Skipping binary file: {file_path}")
            return []

        user_message = (
            f"File: {file_path}\n"
            f"Language: {self._detect_language(file_path)}\n\n"
            f"--- CODE ---\n{content}"
        )

        try:
            response = client.chat.completions.create(
                model=AZURE_OPENAI_DEPLOYMENT,
                messages=[
                    {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.2,
                max_tokens=3000,
            )

            response_text = response.choices[0].message.content or "[]"
            
            # Parse JSON response
            try:
                issues_data = json.loads(response_text)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON response for {file_path}")
                return []

            if not isinstance(issues_data, list):
                logger.warning(f"Response is not a list for {file_path}")
                return []

            # Convert to CodeIssue objects
            issues = []
            for issue_data in issues_data:
                try:
                    severity = IssueSeverity(issue_data.get("severity", "MEDIUM"))
                    category = IssueCategory(issue_data.get("category", "bug"))
                    agent_role = self._infer_agent_role(file_path, category)

                    issue = CodeIssue(
                        file_path=file_path,
                        line_start=int(issue_data.get("line_start", 0)),
                        line_end=int(issue_data.get("line_end", 0)),
                        severity=severity,
                        category=category,
                        description=issue_data.get("description", ""),
                        code_snippet=issue_data.get("code_snippet", ""),
                        suggestion=issue_data.get("suggestion"),
                        agent_role=agent_role,
                    )
                    issues.append(issue)
                except (ValueError, KeyError) as e:
                    logger.warning(f"Could not parse issue data: {e}")
                    continue

            return issues

        except Exception as e:
            logger.error(f"Error reviewing file {file_path}: {e}")
            return []

    @staticmethod
    def _detect_language(file_path: str) -> str:
        """Detect programming language from file extension"""
        ext_to_lang = {
            ".py": "Python",
            ".js": "JavaScript",
            ".jsx": "JavaScript",
            ".ts": "TypeScript",
            ".tsx": "TypeScript",
            ".java": "Java",
            ".cpp": "C++",
            ".c": "C",
            ".go": "Go",
            ".rs": "Rust",
            ".sql": "SQL",
            ".sh": "Bash",
            ".yml": "YAML",
            ".yaml": "YAML",
            ".json": "JSON",
            ".md": "Markdown",
        }
        for ext, lang in ext_to_lang.items():
            if file_path.endswith(ext):
                return lang
        return "Unknown"

    def scan_generated_code(self) -> HealerResult:
        """
        Main entry point: scan all generated code and return results.
        """
        import time
        start_time = time.time()

        logger.info(f"🔍 Healer Agent starting code review for project {self.project_id}")

        files = self._get_generated_files()
        logger.info(f"Found {len(files)} files to review")

        self.issues = []
        for file_path, content in files:
            logger.debug(f"Reviewing {file_path}")
            file_issues = self._review_file(file_path, content)
            self.issues.extend(file_issues)
            self.files_reviewed += 1

        # Aggregate statistics
        issues_by_severity = {}
        issues_by_category = {}

        for issue in self.issues:
            severity_key = issue.severity.value
            category_key = issue.category.value

            issues_by_severity[severity_key] = issues_by_severity.get(severity_key, 0) + 1
            issues_by_category[category_key] = issues_by_category.get(category_key, 0) + 1

        execution_time = time.time() - start_time

        result = HealerResult(
            project_id=self.project_id,
            total_files_reviewed=self.files_reviewed,
            total_issues_found=len(self.issues),
            issues_by_severity=issues_by_severity,
            issues_by_category=issues_by_category,
            issues=self.issues,
            timestamp=datetime.utcnow().isoformat(),
            execution_time_seconds=execution_time,
        )

        logger.info(
            f"✅ Healer Agent completed. Found {len(self.issues)} issues "
            f"in {self.files_reviewed} files ({execution_time:.2f}s)"
        )
        logger.info(f"Issues by severity: {issues_by_severity}")
        logger.info(f"Issues by category: {issues_by_category}")

        return result


# ==========================================
# ORCHESTRATION INTEGRATION
# ==========================================
async def run_healer_and_coordinate_fixes(
    project_id: str,
    director_ai,  # DirectorAI instance
    task_ledger,  # TaskLedger instance
    agents: Dict,  # Dict of agents
) -> HealerResult:
    """
    Run healer agent, then coordinate with Director to fix issues.
    
    Flow:
    1. Healer scans all generated code
    2. Returns list of issues grouped by agent role
    3. Director creates new task ledgers for each affected agent
    4. Director restarts agents with fix tasks
    5. Healer returns results (executes only once)
    """
    healer = HealerAgent(project_id)
    result = healer.scan_generated_code()

    if result.total_issues_found == 0:
        logger.info("✅ No issues found! Code quality is excellent.")
        return result

    logger.info(f"🔧 Coordinating fixes for {result.total_issues_found} issues...")

    # Group issues by agent role
    issues_by_agent = {}
    for issue in result.issues:
        agent_role = issue.agent_role or "backend_engineer"
        if agent_role not in issues_by_agent:
            issues_by_agent[agent_role] = []
        issues_by_agent[agent_role].append(issue)

    # Ask Director to restart agents with fix tasks
    for agent_role, issues in issues_by_agent.items():
        issue_summary = "\n".join([
            f"- [{issue.severity.value}] {issue.category.value}: {issue.description} (Line {issue.line_start})"
            for issue in issues
        ])

        fix_task = (
            f"Review and fix the following issues in your generated code:\n\n{issue_summary}\n\n"
            f"Fix each issue completely. Do not create placeholders."
        )

        logger.info(f"📋 Sending {len(issues)} issues to {agent_role}")

        # Director will restart the agent with the fix task
        if hasattr(director_ai, 'restart_agent_for_fix'):
            await director_ai.restart_agent_for_fix(
                agent_role=agent_role,
                fix_task=fix_task,
                original_ledger=task_ledger,
                issues=issues,
            )

    return result


if __name__ == "__main__":
    # For testing
    logging.basicConfig(level=logging.INFO)
    import asyncio

    project_id = "test-project-123"
    healer = HealerAgent(project_id)
    result = healer.scan_generated_code()
    
    print(json.dumps(result.to_dict(), indent=2))
