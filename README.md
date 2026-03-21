# AI Code Review Agent

An autonomous multi-agent system that reviews GitHub Pull Requests, identifies issues by severity, and generates targeted code fixes — all via a single REST API call.

---

## Architecture

```
POST /review
     │
     ▼
┌─────────────────────┐
│   Code Review Agent  │  ← Fetches PR files from GitHub
│   (GPT-4o)          │    Identifies ALL issues (bugs, security, style, logic)
└────────┬────────────┘
         │ ReviewResult + file cache
         ▼
┌─────────────────────┐
│   Director Agent    │  ← Routes issues by severity
└────────┬────────────┘
         │
    ┌────┴────┐
    ▼         ▼
LOW issues  HIGH issues
(GPT-4o-mini) (GPT-4o)
    │         │
    └────┬────┘
         ▼
┌─────────────────────┐
│   Fixer Agent       │  ← Generates unified diffs per issue
└────────┬────────────┘
         │
         ▼
    FinalReport
  (patches + combined diff)
```

| Agent | Model | Responsibility |
|---|---|---|
| `CodeReviewAgent` | GPT-4o | Fetch PR files, detect all issues |
| `DirectorAgent` | — | Route by severity, collect patches |
| `Fixer` | GPT-4o / GPT-4o-mini | Generate targeted code fixes |

---

## Features

- **Automated PR review** — fetches diffs and full file content directly from GitHub
- **Severity routing** — `LOW` (style, minor bugs) → GPT-4o-mini; `HIGH` (security, logic) → GPT-4o
- **Unified diff output** — patches pipe directly into `git apply`
- **FastAPI REST interface** — single endpoint, structured JSON response

---

## Project Structure

```
.
├── main.py               # FastAPI entrypoint
├── code_review_agent.py  # Fetches PR files, runs GPT-4o review
├── director_agent.py     # Severity-based routing, assembles FinalReport
├── fixer.py              # Generates diffs using appropriate model
├── models.py             # Pydantic models (Issue, FilePatch, FinalReport, ...)
└── requirements.txt
```

---

## Quickstart

### 1. Clone & install

```bash
git clone https://github.com/your-org/code-review-agent.git
cd code-review-agent
pip install -r requirements.txt
```

### 2. Configure environment

Create a `.env` file:

```env
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx

AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your_api_key

AZURE_OPENAI_DEPLOYMENT_GPT4O=gpt-4o
AZURE_OPENAI_DEPLOYMENT_GPT4O_MINI=gpt-4o-mini
```

### 3. Run

```bash
uvicorn main:app --reload
```

---

## API

### `POST /review`

Trigger a full review of a GitHub Pull Request.

**Request**

```json
{
  "pr_url": "https://github.com/owner/repo/pull/42"
}
```

**Response** — `FinalReport`

```json
{
  "pr_url": "https://github.com/owner/repo/pull/42",
  "repo": "owner/repo",
  "total_issues": 5,
  "low_severity": 3,
  "high_severity": 2,
  "patches": [
    {
      "file_path": "src/auth.py",
      "issue_id": "uuid",
      "severity": "HIGH",
      "model_used": "gpt-4o",
      "diff": "--- a/src/auth.py\n+++ b/src/auth.py\n...",
      "explanation": "[HIGH] SECURITY — src/auth.py L14–18: SQL injection vulnerability"
    }
  ],
  "combined_diff": "--- a/src/auth.py\n..."
}
```

### `GET /health`

```json
{ "status": "ok" }
```

---

## Applying Patches

The `combined_diff` field is a standard unified diff. Apply all fixes at once:

```bash
echo '<combined_diff content>' | git apply
```

Or apply per-file patches selectively from the `patches` array.

---

## Data Models

```
Issue
  ├── issue_id      UUID
  ├── file_path     str
  ├── line_start    int
  ├── line_end      int
  ├── severity      LOW | HIGH
  ├── category      security | logic | bug | style
  ├── description   str
  └── code_snippet  str

FilePatch
  ├── file_path     str
  ├── issue_id      str
  ├── severity      LOW | HIGH
  ├── model_used    str
  ├── diff          str  (unified diff)
  └── explanation   str

FinalReport
  ├── pr_url         str
  ├── repo           str
  ├── total_issues   int
  ├── low_severity   int
  ├── high_severity  int
  ├── patches        list[FilePatch]
  └── combined_diff  str
```

---

## Requirements

- Python 3.10+
- Azure OpenAI resource with `gpt-4o` and `gpt-4o-mini` deployments
- GitHub Personal Access Token (read access to target repos)

---

## License

MIT
