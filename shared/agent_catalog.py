AGENT_CATALOG = [
    {
        "id": "backend-engineer-v1",
        "role": "Backend Engineer",
        "tier": 1,
        "description": "Builds REST APIs, microservices, and authentication flows. Outputs OpenAPI 3.0 contracts consumed by the Frontend Engineer.",
        "model_tier": "intermediate",          # maps to GPT-4o-mini
        "mcp_tools": ["github-file-write", "code-sandbox", "azure-sql"],
        "reputation_score": 0.87,
        "tags": ["api", "auth", "microservices"]
    },
    {
        "id": "frontend-engineer-v1",
        "role": "Frontend Engineer",
        "tier": 1,
        "description": "Builds React/Next.js components with accessibility compliance. Consumes the Backend Engineer's OpenAPI contract.",
        "model_tier": "intermediate",
        "mcp_tools": ["github-file-write", "code-sandbox"],
        "reputation_score": 0.91,
        "tags": ["react", "ui", "nextjs"]
    },
    {
        "id": "database-architect-v1",
        "role": "Database Architect",
        "tier": 1,
        "description": "Designs schemas, indexing strategy, and migration scripts for relational and document databases.",
        "model_tier": "complex",               # GPT-4o
        "mcp_tools": ["azure-sql", "cosmos-db", "github-file-write"],
        "reputation_score": 0.83,
        "tags": ["schema", "migrations", "indexing"]
    },
    {
        "id": "security-reviewer-v1",
        "role": "Security Reviewer",
        "tier": 2,
        "description": "Performs OWASP-aligned code review on all generated code. Scans for secrets, IAM misconfigurations, and injection vulnerabilities.",
        "model_tier": "complex",
        "mcp_tools": ["github-read", "code-sandbox"],
        "reputation_score": 0.95,
        "tags": ["owasp", "security", "iam"]
    },
    {
        "id": "qa-engineer-v1",
        "role": "QA Engineer",
        "tier": 2,
        "description": "Generates unit tests, integration tests, and end-to-end scenario tests. Runs them in isolated ACA Jobs containers.",
        "model_tier": "intermediate",
        "mcp_tools": ["code-sandbox", "github-file-write"],
        "reputation_score": 0.89,
        "tags": ["testing", "coverage", "e2e"]
    },
    {
        "id": "devops-engineer-v1",
        "role": "DevOps Engineer",
        "tier": 2,
        "description": "Generates Dockerfiles, Bicep/ARM templates, and GitHub Actions workflows for CI/CD.",
        "model_tier": "intermediate",
        "mcp_tools": ["github-file-write", "azure-devops", "acr"],
        "reputation_score": 0.86,
        "tags": ["docker", "bicep", "ci-cd"]
    },
    {
        "id": "healer-agent-v1",
        "role": "Healer Agent",
        "tier": 2,
        "description": "Performs root cause analysis on test failures and generates targeted patches. Always dispatched at GPT-4o or higher.",
        "model_tier": "high-reasoning",        # GPT-4o + o1-preview
        "mcp_tools": ["code-sandbox", "github-file-write"],
        "reputation_score": 0.80,
        "tags": ["debugging", "repair", "root-cause"]
    },
    {
        "id": "cost-optimizer-v1",
        "role": "Cost Optimizer",
        "tier": 2,
        "description": "Wraps every model call to route tasks to the cheapest capable model. Tracks cumulative token spend in real time.",
        "model_tier": "simple",                # Phi-4 for classification
        "mcp_tools": [],
        "reputation_score": 0.92,
        "tags": ["cost", "routing", "budget"]
    },
]