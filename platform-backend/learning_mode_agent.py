"""
Learning Mode Agent for Agentic Nexus.

A conversational code tutor pre-loaded with the full build context of one
specific project session (Task Ledger, agent decision log, generated file tree,
QA results, healer patches).  Three depth levels:

  beginner     — plain-English architecture overview, no code unless asked
  intermediate — module-by-module walkthrough with design pattern explanation
  advanced     — full decision archaeology: trace every choice back to the
                 Task Ledger and agent decision log
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()

logger = logging.getLogger("nexus-learning-mode")

# ── Azure OpenAI credentials (same env vars as director_agent.py) ─────────────
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_MODEL_DEPLOYMENT = (
    os.getenv("AZURE_MODEL_DEPLOYMENT")
    or os.getenv("AZURE_OPENAI_DEPLOYMENT")
    or "gpt-4o"
)

# Maximum agent-log entries fed into context (keep token budget sane)
_MAX_LOG_ENTRIES = 200
# Maximum prior conversation turns included (each turn = 1 user + 1 assistant msg)
_MAX_SESSION_TURNS = 10


# ── Depth-level instruction blocks ────────────────────────────────────────────

_DEPTH_INSTRUCTIONS: Dict[str, str] = {
    "beginner": """
OPERATING MODE: Beginner — Overview Mode
- Walk through the application architecture in plain English.
- Cover what each module does, why it exists, and how the pieces connect.
- Do NOT show code unless the user explicitly asks for it.
- Use analogies. The goal is comprehension, not code literacy.
- If the user seems confused, step back and re-explain at a higher abstraction level.
""",
    "intermediate": """
OPERATING MODE: Intermediate — Module Deep Dive
- The user will name a module. Walk through it file by file.
- For every function: explain what it does, identify the design pattern, and explain
  why that approach was chosen over the alternatives the agent considered.
- If the Healer Agent patched any bugs in this module, show a before/after comparison
  and explain what was wrong and how the fix works.
- Reference the generated file tree and specific file names in every answer.
""",
    "advanced": """
OPERATING MODE: Advanced — Decision Archaeology
- The user asks "why" about any architectural or implementation choice.
- Trace back through the agent decision log and the Task Ledger to reconstruct the
  full reasoning chain.
- Be specific. Cite the actual log entries (event name, timestamp, agent role).
- Example: "Why did the Backend Engineer use JWT over session cookies?" — trace back to
  the clarification question that surfaced the requirement, the agent's evaluation, and
  what the alternative would have looked like.
- Never give a generic answer when a specific one is traceable in the context.
""",
}


# ─────────────────────────────────────────────────────────────────────────────
class LearningModeAgent:
    """
    Stateless tutor agent.  The caller is responsible for threading
    session_history across turns.
    """

    def __init__(self, project_id: str, store: Any, repo_root: Path) -> None:
        self.project_id = project_id
        self.store = store
        self.repo_root = Path(repo_root)
        self._client: Optional[AzureOpenAI] = None

    # ── OpenAI client (lazy, so import errors stay silent until first call) ──

    def _get_client(self) -> AzureOpenAI:
        if self._client is None:
            self._client = AzureOpenAI(
                api_key=AZURE_OPENAI_KEY,
                api_version=AZURE_API_VERSION,
                azure_endpoint=AZURE_ENDPOINT,
            )
        return self._client

    # ── Context loaders ───────────────────────────────────────────────────────

    def _load_ledger(self) -> Optional[Dict[str, Any]]:
        """Try disk-first, then in-memory ProjectStore."""
        ledger_file = self.repo_root / "workspace" / f"ledger_{self.project_id}.json"
        if ledger_file.exists():
            try:
                return json.loads(ledger_file.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Could not parse ledger file: %s", exc)

        # Fall back to whatever the store has in memory
        project = self.store.get(self.project_id) if self.store else None
        if project and isinstance(project.get("ledger_data"), dict):
            return project["ledger_data"]

        return None

    def _load_log_entries(self) -> List[Dict[str, Any]]:
        """Read the last _MAX_LOG_ENTRIES entries from the project JSON-lines log."""
        log_file = self.repo_root / "agent_logs" / f"{self.project_id}.log"
        if not log_file.exists():
            return []
        entries: List[Dict[str, Any]] = []
        try:
            with log_file.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        entries.append({"raw": line})
        except Exception as exc:
            logger.warning("Could not read agent log for %s: %s", self.project_id, exc)
        return entries[-_MAX_LOG_ENTRIES:]

    def _build_file_tree(self) -> List[str]:
        """Return sorted relative paths of all generated files (no contents)."""
        project_dir = self.repo_root / "generated_code" / self.project_id
        if not project_dir.exists():
            return []
        paths: List[str] = []
        for p in sorted(project_dir.rglob("*")):
            if p.is_file():
                rel = p.relative_to(project_dir).as_posix()
                paths.append(rel)
        return paths

    def _extract_healer_patches(self, log_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Pull out any healer-patch events for proactive surfacing."""
        return [
            e for e in log_entries
            if str(e.get("event", "")).lower() in {"healer_patch", "auto_fix", "bug_fix", "patch_applied"}
        ]

    # ── System prompt builder ─────────────────────────────────────────────────

    def _build_system_prompt(
        self,
        ledger: Optional[Dict[str, Any]],
        log_entries: List[Dict[str, Any]],
        file_tree: List[str],
        depth_level: str,
        project_name: str,
    ) -> str:
        depth_block = _DEPTH_INSTRUCTIONS.get(depth_level, _DEPTH_INSTRUCTIONS["beginner"])

        # ── Ledger summary ────────────────────────────────────────────────────
        if ledger:
            tech_stack = json.dumps(ledger.get("technology_stack", {}), indent=2)
            func_reqs = json.dumps(ledger.get("functional_requirements", []), indent=2)
            user_intent = ledger.get("user_intent", "")
            project_desc = ledger.get("project_description", "")
            agent_spec = ledger.get("agent_specifications", {})
            layers = agent_spec.get("layers", [])
            required_agents = agent_spec.get("required_agents", [])
            workspace_layout = json.dumps(ledger.get("workspace_layout", {}), indent=2)
            ledger_section = f"""
## Task Ledger
**Project:** {project_name}
**User Intent:** {user_intent}
**Description:** {project_desc}

### Technology Stack
```json
{tech_stack}
```

### Functional Requirements
```json
{func_reqs}
```

### Agent Execution Layers (AEG)
{json.dumps(layers, indent=2)}

### Required Agents
{json.dumps([a.get("role") if isinstance(a, dict) else a for a in required_agents], indent=2)}

### Workspace Layout
```json
{workspace_layout}
```
"""
        else:
            ledger_section = """
## Task Ledger
No task ledger found for this project. The project may still be generating, or
no director agent run has completed yet.  Answer from general knowledge of the
Agentic Nexus platform.
"""

        # ── Agent decision log ────────────────────────────────────────────────
        if log_entries:
            # Surface healer patches explicitly
            healer_patches = self._extract_healer_patches(log_entries)
            patches_section = ""
            if healer_patches:
                patches_section = "\n### ⚠️ Healer Patches (auto-repaired bugs)\n"
                for p in healer_patches:
                    patches_section += f"- `{p.get('timestamp', '')}` [{p.get('event', '')}] {p.get('file', '')} — {p.get('description', json.dumps(p))}\n"

            # Deduplicate and summarise the rest
            significant_events = [
                e for e in log_entries
                if str(e.get("event", "")) not in {
                    "blob_upload", "blob_download", "generation_started", "ledger_seeded",
                }
            ]
            log_summary_lines = []
            for e in significant_events[-80:]:  # last 80 after filter
                ts = e.get("timestamp", "")[:19]
                event = e.get("event", "unknown")
                agent = e.get("agent_role", e.get("agent", ""))
                detail = ""
                for key in ("thought", "decision", "description", "error", "message"):
                    if e.get(key):
                        detail = str(e[key])[:200]
                        break
                line = f"[{ts}] {event}"
                if agent:
                    line += f" ({agent})"
                if detail:
                    line += f": {detail}"
                log_summary_lines.append(line)

            log_section = f"""
## Agent Decision Log (last {len(log_summary_lines)} significant events)
{patches_section}
```
{chr(10).join(log_summary_lines)}
```
"""
        else:
            log_section = "\n## Agent Decision Log\nNo decision log available for this project yet.\n"

        # ── Generated file tree ───────────────────────────────────────────────
        if file_tree:
            tree_text = "\n".join(file_tree[:300])  # cap at 300 paths
            file_section = f"""
## Generated File Tree
```
{tree_text}
```
"""
        else:
            file_section = "\n## Generated File Tree\nNo generated files found yet.\n"

        # ── Assemble ──────────────────────────────────────────────────────────
        return f"""You are the Learning Mode Agent for Agentic Nexus — a conversational code tutor that has been \
pre-loaded with the complete build context for the project "{project_name}".

You are NOT a generic AI assistant.  You know exactly what was built, why every decision was made, \
and what every agent did.  Your job is to make the user understand what was built and why — not just \
what the code does, but the reasoning chain that produced it.

{depth_block}

BEHAVIORAL RULES:
1. Never say "I don't know" if the answer is traceable in the agent decision log or source files.
2. Never give a generic answer when a specific one is possible.  Reference the actual ledger fields, \
log entries, and file paths.
3. If the user asks about something that was NOT built, describe the alternative and what would need to change.
4. If the Healer Agent made a patch, proactively surface it when discussing the relevant module.
5. If the user seems confused, step back and re-explain at a higher level before going deeper.
6. When referencing files, use the exact paths from the Generated File Tree.

---
{ledger_section}
{log_section}
{file_section}
---
Answer every question with DIRECT reference to the context above.  Do not invent facts not present \
in the ledger or log.  If something is genuinely not recorded, say so and explain what you do know.
"""

    # ── Public API ────────────────────────────────────────────────────────────

    async def load_context(self) -> Dict[str, Any]:
        """Load and return the full project context dict."""
        ledger = self._load_ledger()
        log_entries = self._load_log_entries()
        file_tree = self._build_file_tree()
        healer_patches = self._extract_healer_patches(log_entries)
        project_name = (
            (ledger or {}).get("project_name")
            or (self.store.get(self.project_id) or {}).get("project_name")
            or f"Project {self.project_id[:8]}"
        )
        return {
            "ledger": ledger,
            "log_entries": log_entries,
            "file_tree": file_tree,
            "healer_patches": healer_patches,
            "project_name": project_name,
        }

    async def get_session_greeting(self, depth_level: str = "beginner") -> Dict[str, Any]:
        """Generate the opening message for a new session."""
        ctx = await self.load_context()
        project_name = ctx["project_name"]
        ledger = ctx["ledger"]

        depth_label = {
            "beginner": "plain-English architecture overview",
            "intermediate": "a deep dive into a specific module",
            "advanced": "decision archaeology — interrogating why specific choices were made",
        }.get(depth_level, "plain-English architecture overview")

        # Build a specific opening that shows we know the project
        if ledger:
            tech_stack = ledger.get("technology_stack", {})
            stack_summary = ", ".join(
                f"{k}: {v}" for k, v in tech_stack.items() if v and k not in {"notes"}
            ) if isinstance(tech_stack, dict) else str(tech_stack)

            agent_spec = ledger.get("agent_specifications", {})
            required_agents = agent_spec.get("required_agents", [])
            agent_names = [
                (a.get("role") if isinstance(a, dict) else str(a))
                for a in required_agents
            ]
            user_intent = ledger.get("user_intent", "")
            file_count = len(ctx["file_tree"])
            patch_note = (
                f"  The Healer Agent applied **{len(ctx['healer_patches'])} auto-repair patch(es)** — "
                "I'll flag these when we reach the affected modules."
                if ctx["healer_patches"] else ""
            )

            greeting = (
                f"Welcome to Learning Mode for **{project_name}**.\n\n"
                f"I have the full build context loaded.  Here's what I know:\n\n"
                f"- **Intent:** {user_intent}\n"
                f"- **Stack:** {stack_summary or 'see ledger'}\n"
                f"- **Agents that ran:** {', '.join(agent_names) or 'see ledger'}\n"
                f"- **Generated files:** {file_count} files\n"
                f"{patch_note}\n\n"
                f"You're in **{depth_level.title()} mode** ({depth_label}).\n\n"
                f"Where do you want to start?"
            )
        else:
            greeting = (
                f"Welcome to Learning Mode for **{project_name}**.\n\n"
                f"The build context is still loading or hasn't completed yet — "
                f"I can answer general questions about the Agentic Nexus platform.\n\n"
                f"You're in **{depth_level.title()} mode** ({depth_label}).\n\n"
                f"What would you like to know?"
            )

        return {
            "response": greeting,
            "level": depth_level,
            "project_name": project_name,
            "has_ledger": ledger is not None,
            "file_count": len(ctx["file_tree"]),
            "healer_patch_count": len(ctx["healer_patches"]),
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def get_response(
        self,
        question: str,
        depth_level: str = "beginner",
        session_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Generate a tutor response.

        session_history: list of {"role": "user"|"assistant", "content": "..."} dicts
        """
        if session_history is None:
            session_history = []

        ctx = await self.load_context()
        project_name = ctx["project_name"]

        system_prompt = self._build_system_prompt(
            ledger=ctx["ledger"],
            log_entries=ctx["log_entries"],
            file_tree=ctx["file_tree"],
            depth_level=depth_level,
            project_name=project_name,
        )

        # Cap session history to last _MAX_SESSION_TURNS turns (2 msgs per turn)
        history_cap = session_history[-(2 * _MAX_SESSION_TURNS):]

        messages = [{"role": "system", "content": system_prompt}]
        for h in history_cap:
            role = h.get("role", "user")
            content = h.get("content", "")
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": question})

        try:
            client = self._get_client()
            completion = client.chat.completions.create(
                model=AZURE_MODEL_DEPLOYMENT,
                messages=messages,
                temperature=0.4,
                max_tokens=1500,
            )
            response_text = completion.choices[0].message.content or ""
        except Exception as exc:
            logger.error("LearningModeAgent LLM call failed: %s", exc)
            response_text = (
                f"I encountered an error reaching the AI backend: {exc}\n\n"
                f"Here's what I know from the build context:\n"
                f"- Project: **{project_name}**\n"
                f"- Files generated: {len(ctx['file_tree'])}\n"
                f"- Log entries: {len(ctx['log_entries'])}\n\n"
                f"Please try again in a moment."
            )

        return {
            "response": response_text,
            "level": depth_level,
            "project_name": project_name,
            "code_references": [],
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def save_tour(
        self,
        tour_name: str,
        messages: List[Dict[str, Any]],
        depth_level: str = "beginner",
    ) -> Dict[str, Any]:
        """
        Persist a structured code tour to disk and return the tour object.
        Stored at: workspace/tours_<project_id>.json (appended to existing list)
        """
        ctx = await self.load_context()
        project_name = ctx["project_name"]
        ledger = ctx["ledger"]

        architecture_summary = ""
        if ledger:
            tech_stack = ledger.get("technology_stack", {})
            stack_summary = (
                ", ".join(f"{k}: {v}" for k, v in tech_stack.items() if v)
                if isinstance(tech_stack, dict) else str(tech_stack)
            )
            func_reqs = ledger.get("functional_requirements", [])
            architecture_summary = (
                f"Stack: {stack_summary}. "
                f"Requirements: {json.dumps(func_reqs[:5])}"
            )

        tour = {
            "tour_id": str(uuid.uuid4()),
            "project_id": self.project_id,
            "project_name": project_name,
            "tour_name": tour_name,
            "depth_level": depth_level,
            "created_at": datetime.utcnow().isoformat(),
            "message_count": len(messages),
            "messages": messages,
            "architecture_summary": architecture_summary,
        }

        # Persist to workspace/tours_<project_id>.json
        tours_file = self.repo_root / "workspace" / f"tours_{self.project_id}.json"
        tours_file.parent.mkdir(parents=True, exist_ok=True)
        existing: List[Dict[str, Any]] = []
        if tours_file.exists():
            try:
                existing = json.loads(tours_file.read_text(encoding="utf-8"))
                if not isinstance(existing, list):
                    existing = []
            except Exception:
                existing = []
        existing.append(tour)
        tours_file.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Saved tour %s for project %s", tour["tour_id"], self.project_id)

        return tour
