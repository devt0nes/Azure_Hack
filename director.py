# director.py
from config import openai_client, GPT4O, MINI
import json

DIRECTOR_SYSTEM_PROMPT = """
You are the Director of a multi-agent software build platform.
Clarify the user's app idea in EXACTLY 2-3 focused questions — no more, no less.

Cover these 5 axes across your questions:
  1. Functional scope — what does the app actually do
  2. Target users — who uses it, what scale
  3. Tech constraints — preferred stack, anything forbidden
  4. Integrations — third-party APIs, databases
  5. Quality/compliance — performance, budget, security

If the user mentions a risky tech choice (no auth, plaintext passwords,
NoSQL for financial data), output a GUARDRAIL before your next question.

Respond ONLY with valid JSON — no markdown, no extra text.

If you need more info:
  {"action": "ASK", "question": "your question here"}

If a tech choice is risky:
  {"action": "GUARDRAIL", "risk": "one line risk summary",
   "recommendation": "what you suggest instead",
   "question": "challenge + your next question"}

Once you have enough info (after 2-3 exchanges):
  {"action": "TASK_LEDGER_COMPLETE", "task_ledger": {
     "user_intent": "...",
     "functional_requirements": ["...", "..."],
     "non_functional_requirements": {"performance": "...", "budget": "..."},
     "tech_constraints": {"preferred": "...", "forbidden": "..."},
     "integration_targets": ["..."]
  }}
"""

AEG_PROMPT = """
Decompose this Task Ledger into an Agent Execution Graph (AEG).

STRICT RULES:
  - Produce exactly 5 to 7 agent nodes
  - NO circular dependencies — if agent A depends on B, B cannot depend on A
  - Each node must specify: agent_id, role, inputs[], outputs[], token_budget, model_preference
  - Edges must only flow from the producer of a value to its consumer
  - model_preference must be one of: gpt-4o-mini, gpt-4o
    Use gpt-4o only for auth, security, and architecture-level tasks
    Use gpt-4o-mini for API, schema, component, and test tasks

Available agent roles:
  Backend Engineer, Frontend Engineer, Database Architect,
  Security Reviewer, QA Engineer, DevOps Engineer, Documentation Writer

Return ONLY valid JSON:
{"nodes": [...], "edges": [{"from_agent": "...", "to_agent": "..."}]}
"""

async def run_clarification(conversation_history: list) -> dict:
    response = await openai_client.chat.completions.create(
        model=GPT4O,
        messages=[{"role": "system", "content": DIRECTOR_SYSTEM_PROMPT}]
                 + conversation_history,
        temperature=0.3,
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)


def has_cycle(nodes: list, edges: list) -> bool:
    graph = {n["agent_id"]: [] for n in nodes}
    for e in edges:
        graph[e["from_agent"]].append(e["to_agent"])
    visited, rec = set(), set()

    def dfs(node):
        visited.add(node)
        rec.add(node)
        for nb in graph.get(node, []):
            if nb not in visited and dfs(nb):
                return True
            elif nb in rec:
                return True
        rec.discard(node)
        return False

    return any(dfs(n) for n in graph if n not in visited)


async def generate_aeg(task_ledger: dict) -> dict:
    response = await openai_client.chat.completions.create(
        model=GPT4O,
        messages=[
            {"role": "system", "content": AEG_PROMPT},
            {"role": "user", "content": json.dumps(task_ledger)}
        ],
        temperature=0.2,
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)