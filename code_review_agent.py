"""
Code Review Agent.
Fetches changed files from a GitHub PR, asks GPT-4o to find and tag all issues.
"""
from __future__ import annotations
import os, json, re
import httpx
from openai import AzureOpenAI
from models import Issue, ReviewResult, Severity

GITHUB_TOKEN          = os.environ["GITHUB_TOKEN"]
AZURE_OPENAI_ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"]
AZURE_OPENAI_API_KEY  = os.environ["AZURE_OPENAI_API_KEY"]
GPT4O_DEPLOYMENT      = os.environ.get("AZURE_OPENAI_DEPLOYMENT_GPT4O", "gpt-4o")

_oai = AzureOpenAI(
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_key=AZURE_OPENAI_API_KEY,
    api_version="2024-02-01",
)

_GH_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}

REVIEW_SYSTEM_PROMPT = """
You are a senior code reviewer. Analyse the provided diff and full file content.
Identify ALL issues: bugs, security vulnerabilities, logic errors, style problems.

Return ONLY a JSON array. Each element must have exactly these keys:
  file_path, line_start, line_end, severity, category, description, code_snippet

severity: "LOW"  → style, minor bugs, missing null-checks, dead code
          "HIGH" → security holes, logic errors, data races, wrong algorithms, leaks

category: one of  security | logic | bug | style

No markdown. No explanation outside the JSON array.
""".strip()


def _parse_pr_url(pr_url: str) -> tuple[str, str, int]:
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)", pr_url)
    if not m:
        raise ValueError(f"Invalid PR URL: {pr_url}")
    return m.group(1), m.group(2), int(m.group(3))


def _fetch_pr_files(owner: str, repo: str, pr_number: int) -> list[dict]:
    url  = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"
    resp = httpx.get(url, headers=_GH_HEADERS, timeout=30)
    resp.raise_for_status()

    enriched = []
    for f in resp.json():
        if f.get("status") == "removed":
            continue
        content = ""
        if raw_url := f.get("raw_url", ""):
            try:
                content = httpx.get(raw_url, headers=_GH_HEADERS, timeout=20).text
            except Exception:
                pass
        enriched.append({
            "filename": f["filename"],
            "patch":    f.get("patch", ""),
            "content":  content,
        })
    return enriched


def _review_file(filename: str, patch: str, content: str) -> list[Issue]:
    user_msg = (
        f"File: {filename}\n\n"
        f"--- DIFF ---\n{patch or '(no diff)'}\n\n"
        f"--- FULL FILE ---\n{content[:8000]}"
    )
    resp = _oai.chat.completions.create(
        model=GPT4O_DEPLOYMENT,
        messages=[
            {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.1,
        max_tokens=2000,
    )
    raw    = resp.choices[0].message.content or "[]"
    parsed = json.loads(raw)
    items  = parsed if isinstance(parsed, list) else parsed.get("issues", [])
    return [
        Issue(file_path=filename, **{k: v for k, v in i.items() if k != "file_path"})
        for i in items
    ]


def review_pr(pr_url: str) -> tuple[ReviewResult, dict[str, str]]:
    """
    Returns (ReviewResult, {filename: full_content}) so fixer can
    access full file content without re-fetching.
    """
    owner, repo, pr_number = _parse_pr_url(pr_url)
    files = _fetch_pr_files(owner, repo, pr_number)

    all_issues: list[Issue]  = []
    cache: dict[str, str]    = {}

    for f in files:
        cache[f["filename"]] = f["content"]
        try:
            all_issues.extend(_review_file(f["filename"], f["patch"], f["content"]))
        except Exception as e:
            print(f"[CodeReviewAgent] Skipping {f['filename']}: {e}")

    return ReviewResult(
        pr_url=pr_url,
        repo=f"{owner}/{repo}",
        issues=all_issues,
        total_files_reviewed=len(files),
    ), cache