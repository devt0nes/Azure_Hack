"""
Fixer.
Receives an Issue + full file content, calls the right model, returns a diff.
"""
from __future__ import annotations
import os, difflib
from openai import AzureOpenAI
from models import Issue, FilePatch, Severity

AZURE_OPENAI_ENDPOINT     = os.environ["AZURE_OPENAI_ENDPOINT"]
AZURE_OPENAI_API_KEY      = os.environ["AZURE_OPENAI_API_KEY"]
GPT4O_DEPLOYMENT          = os.environ.get("AZURE_OPENAI_DEPLOYMENT_GPT4O",      "gpt-4o")
GPT4O_MINI_DEPLOYMENT     = os.environ.get("AZURE_OPENAI_DEPLOYMENT_GPT4O_MINI", "gpt-4o-mini")

_oai = AzureOpenAI(
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_key=AZURE_OPENAI_API_KEY,
    api_version="2024-02-01",
)

FIX_SYSTEM_PROMPT = """
You are an expert software engineer. You will be given a file and a specific issue to fix.

Return ONLY the complete corrected file — no markdown fences, no explanation, no commentary.
Make the fix minimal and targeted. Do not reformat or change unrelated code.
""".strip()


def _make_diff(original: str, fixed: str, filepath: str) -> str:
    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        fixed.splitlines(keepends=True),
        fromfile=f"a/{filepath}",
        tofile=f"b/{filepath}",
    )
    return "".join(diff)


def fix(issue: Issue, use_mini: bool, full_file_content: str = "") -> FilePatch:
    model   = GPT4O_MINI_DEPLOYMENT if use_mini else GPT4O_DEPLOYMENT
    content = full_file_content or issue.code_snippet

    user_msg = (
        f"File: {issue.file_path}\n"
        f"Lines {issue.line_start}–{issue.line_end}\n"
        f"Category: {issue.category}\n"
        f"Issue: {issue.description}\n\n"
        f"--- FULL FILE ---\n{content}"
    )

    resp = _oai.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": FIX_SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.1,
        max_tokens=4000,
    )

    fixed_code  = resp.choices[0].message.content or content
    diff        = _make_diff(content, fixed_code, issue.file_path)

    return FilePatch(
        file_path=issue.file_path,
        issue_id=issue.issue_id,
        severity=issue.severity,
        model_used=model,
        diff=diff,
        explanation=(
            f"[{issue.severity}] {issue.category.upper()} — "
            f"{issue.file_path} L{issue.line_start}–{issue.line_end}: "
            f"{issue.description}"
        ),
    )