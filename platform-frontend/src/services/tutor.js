const TUTOR_API_URL = import.meta.env.VITE_TUTOR_API_URL || ''
const TUTOR_API_KEY = import.meta.env.VITE_TUTOR_API_KEY || ''

export async function askTutor({ projectId, question, context = {} }) {
  if (!TUTOR_API_URL) {
    // Return mock response when no API configured
    return {
      response: generateMockResponse(question),
      level: 'overview',
      timestamp: new Date().toISOString(),
    }
  }

  const response = await fetch(`${TUTOR_API_URL}/tutor/ask`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(TUTOR_API_KEY && { Authorization: `Bearer ${TUTOR_API_KEY}` }),
    },
    body: JSON.stringify({
      project_id: projectId,
      question,
      context,
    }),
  })

  if (!response.ok) {
    throw new Error('Tutor request failed')
  }

  return response.json()
}

function generateMockResponse(question) {
  const lowerQ = question.toLowerCase()

  if (lowerQ.includes('explain') && lowerQ.includes('build')) {
    return `# Build Architecture Overview

This is a **multi-agent orchestration system** where specialized AI agents collaborate to build full-stack applications.

## Key Components

**🎯 Director Agent**
- Clarifies user requirements through conversation
- Builds the Task Ledger (execution plan)
- Constructs the Agent Execution Graph (AEG)
- Orchestrates agent dependencies

**🏗️ Specialist Agents**
- **Frontend Engineer**: React components, styling, routing
- **Backend Engineer**: APIs, databases, authentication
- **QA Agent**: Testing, validation, deployment readiness

**📊 Platform A (This UI)**
- Real-time visualization of agent status
- Cost tracking (tokens + $)
- Live execution logs
- Feedback loop for changes

## Execution Flow

1. You describe what to build via \`/clarify\`
2. Director creates task breakdown
3. AEG shows agent dependencies
4. Agents execute in parallel (when possible)
5. Results merge into deployable bundle
6. QA validates & Healer fixes issues

**Current State**: Mock mode — connect a backend to enable live orchestration.`
  }

  if (lowerQ.includes('aeg') || lowerQ.includes('graph')) {
    return `# Agent Execution Graph (AEG)

The AEG is a **directed acyclic graph (DAG)** representing how agents depend on each other.

**Nodes**: Each agent (color-coded by state)
- 🔵 PENDING: Waiting for dependencies
- 🟠 RUNNING: Currently executing
- 🟢 COMPLETED: Task finished successfully
- 🔴 FAILED: Encountered errors

**Edges**: Dependencies (Agent A must finish before Agent B starts)

**Benefits**:
- Maximize parallelism (independent agents run simultaneously)
- Clear visualization of bottlenecks
- Easy crash recovery (re-run failed node without restarting everything)`
  }

  if (lowerQ.includes('cost') || lowerQ.includes('token')) {
    return `# Cost Tracking

Every agent call to GPT-4 (or other LLMs) consumes tokens.

**How it works**:
- Each agent reports tokens used after execution
- SignalR broadcasts cost updates in real-time
- Ticker shows: \`tokens × price-per-token = $ cost\`

**Optimization**:
- Agents use system prompts to stay concise
- Context windows are trimmed (no redundant history)
- Parallel execution reduces wall-clock time

**Current Cost**: $0.063 for ~2500 tokens (example mock data)`
  }

  return `I'm the Learning Mode tutor! I can explain:
- **"Explain this build"** — High-level architecture
- **"What is the AEG?"** — Agent execution graph
- **"How does cost tracking work?"** — Token/$ calculation
- **"Show me the conversation flow"** — Director clarification loop

Ask me anything about the system!`
}
