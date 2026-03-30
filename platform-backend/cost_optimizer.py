from __future__ import annotations

import os
import re
import threading
from enum import Enum
from typing import Any, Dict, List, Optional

from openai import AzureOpenAI


class ModelTier(str, Enum):
    SIMPLE = "simple"
    INTERMEDIATE = "intermediate"
    COMPLEX = "complex"
    HIGH_REASONING = "high-reasoning"


class BudgetCapReached(RuntimeError):
    """Raised when non-critical work should be halted due to budget pressure."""


_ROUTING_KEYWORDS: Dict[ModelTier, List[str]] = {
    ModelTier.HIGH_REASONING: [
        "root cause",
        "feasibility",
        "tradeoff",
        "trade-off",
        "architecture plan",
        "planning",
        "debug strategy",
        "why is",
    ],
    ModelTier.COMPLEX: [
        "auth",
        "authorization",
        "security",
        "threat model",
        "data model",
        "schema design",
        "compliance",
        "multi-tenant",
        "encryption",
    ],
    ModelTier.INTERMEDIATE: [
        "crud",
        "unit test",
        "integration test",
        "config file",
        "refactor",
        "api route",
        "migration",
        "form validation",
    ],
    ModelTier.SIMPLE: [
        "documentation",
        "docs",
        "readme",
        "css",
        "boilerplate",
        "copywriting",
        "comment",
        "rename",
    ],
}


_PROJECT_ID_RE = re.compile(r"\b(project[-_][a-z0-9\-]+)\b", re.IGNORECASE)


def classify_task(task_description: str) -> ModelTier:
    """Classify a task into a routing tier using lightweight heuristics."""
    text = " ".join(str(task_description or "").lower().split())
    if not text:
        return ModelTier.INTERMEDIATE

    for tier in [ModelTier.HIGH_REASONING, ModelTier.COMPLEX, ModelTier.INTERMEDIATE, ModelTier.SIMPLE]:
        for needle in _ROUTING_KEYWORDS[tier]:
            if needle in text:
                return tier

    token_like = len(re.findall(r"\w+", text))
    if token_like <= 18:
        return ModelTier.SIMPLE
    if token_like <= 80:
        return ModelTier.INTERMEDIATE
    return ModelTier.COMPLEX


def _resolve_deployment_for_tier(tier: ModelTier) -> str:
    if tier == ModelTier.SIMPLE:
        return os.getenv("AZURE_DEPLOYMENT_PHI4", "phi-4")
    if tier == ModelTier.INTERMEDIATE:
        return os.getenv("AZURE_DEPLOYMENT_GPT4O_MINI", "gpt-4o-mini")
    if tier == ModelTier.COMPLEX:
        return os.getenv("AZURE_DEPLOYMENT_GPT4O", os.getenv("AZURE_MODEL_DEPLOYMENT", "gpt-4o"))
    return os.getenv("AZURE_DEPLOYMENT_O1_PREVIEW", os.getenv("AZURE_DEPLOYMENT_GPT4O", os.getenv("AZURE_MODEL_DEPLOYMENT", "gpt-4o")))


_CLIENT_LOCK = threading.Lock()
_CLIENT_BY_TIER: Dict[ModelTier, AzureOpenAI] = {}


def get_client(tier: ModelTier) -> AzureOpenAI:
    """Factory for per-tier AzureOpenAI clients (shared endpoint/key, cached by tier)."""
    with _CLIENT_LOCK:
        cached = _CLIENT_BY_TIER.get(tier)
        if cached is not None:
            return cached

        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        api_key = os.getenv("AZURE_OPENAI_KEY") or os.getenv("AZURE_OPENAI_API_KEY")
        api_version = os.getenv("AZURE_OPENAI_API_VERSION") or "2024-05-01-preview"
        if not endpoint or not api_key:
            raise RuntimeError("Azure OpenAI environment variables are not configured")

        client = AzureOpenAI(azure_endpoint=endpoint, api_key=api_key, api_version=api_version)
        _CLIENT_BY_TIER[tier] = client
        return client


class _RoutedCompletionsProxy:
    def __init__(self, routed_client: "RoutedAzureOpenAIClient"):
        self._routed_client = routed_client

    def create(self, **kwargs):
        return self._routed_client._create_completion(**kwargs)


class _RoutedChatProxy:
    def __init__(self, routed_client: "RoutedAzureOpenAIClient"):
        self.completions = _RoutedCompletionsProxy(routed_client)


class RoutedAzureOpenAIClient:
    """Drop-in wrapper around AzureOpenAI.chat.completions.create with cost-aware routing."""

    def __init__(self, *, default_agent_role: str = "unknown_agent", tracker: Optional[Any] = None):
        self.default_agent_role = default_agent_role
        self.tracker = tracker
        self.chat = _RoutedChatProxy(self)

    def _derive_task_description(self, kwargs: Dict[str, Any]) -> str:
        explicit = kwargs.pop("task_description", None)
        if explicit:
            return str(explicit)

        messages = kwargs.get("messages") or []
        if not isinstance(messages, list):
            return ""

        lines: List[str] = []
        for msg in messages[-3:]:
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if isinstance(content, str):
                lines.append(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        lines.append(part["text"])
        return "\n".join(lines)[:1500]

    def _estimate_prompt_tokens(self, messages: Any) -> int:
        if not isinstance(messages, list):
            return 0
        text_parts: List[str] = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if isinstance(content, str):
                text_parts.append(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        text = part.get("text")
                        if isinstance(text, str):
                            text_parts.append(text)
        joined = "\n".join(text_parts)
        if not joined:
            return 0
        # Rough approximation for realtime visibility when API omits usage.
        return max(1, len(joined) // 4)

    def _estimate_completion_tokens(self, response: Any) -> int:
        try:
            choices = getattr(response, "choices", None)
            if not isinstance(choices, list) or not choices:
                return 0
            message = getattr(choices[0], "message", None)
            content = getattr(message, "content", "") if message is not None else ""
            text = str(content or "")
            if not text:
                return 0
            return max(1, len(text) // 4)
        except Exception:
            return 0

    def _infer_project_id_from_text(self, text: str) -> str:
        if not text:
            return ""
        match = _PROJECT_ID_RE.search(text)
        if not match:
            return ""
        return str(match.group(1) or "").strip()

    def _create_completion(self, **kwargs):
        project_id = str(kwargs.pop("project_id", "") or os.getenv("NEXUS_ACTIVE_PROJECT_ID") or "default")
        agent_role = str(kwargs.pop("agent_role", "") or self.default_agent_role or "unknown_agent")
        non_critical = kwargs.pop("non_critical", None)
        task_description = self._derive_task_description(kwargs)
        if project_id.lower() in {"", "default"}:
            inferred_project = self._infer_project_id_from_text(task_description)
            if inferred_project:
                project_id = inferred_project
        chosen_tier = classify_task(task_description)

        if non_critical is None:
            non_critical = chosen_tier in {ModelTier.SIMPLE, ModelTier.INTERMEDIATE}

        if self.tracker and non_critical and self.tracker.should_halt_non_critical(project_id=project_id):
            raise BudgetCapReached(
                f"Budget cap pressure reached for project '{project_id}'. Non-critical task paused for {agent_role}."
            )

        deployment_name = _resolve_deployment_for_tier(chosen_tier)
        kwargs["model"] = deployment_name

        client = get_client(chosen_tier)
        response = client.chat.completions.create(**kwargs)

        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", prompt_tokens + completion_tokens) or (prompt_tokens + completion_tokens))

        if prompt_tokens <= 0:
            prompt_tokens = self._estimate_prompt_tokens(kwargs.get("messages"))
        if completion_tokens <= 0:
            completion_tokens = self._estimate_completion_tokens(response)
        if total_tokens <= 0:
            total_tokens = prompt_tokens + completion_tokens

        if self.tracker:
            self.tracker.record_usage(
                project_id=project_id,
                agent_role=agent_role,
                model_tier=chosen_tier.value,
                model_deployment=deployment_name,
                task_description=task_description[:280],
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )

        return response


def create_routed_client(*, default_agent_role: str, tracker: Optional[Any] = None) -> RoutedAzureOpenAIClient:
    return RoutedAzureOpenAIClient(default_agent_role=default_agent_role, tracker=tracker)