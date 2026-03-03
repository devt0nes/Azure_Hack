# Agentic Nexus - No-Code/Low-Code Application Builder

## Overview

Agentic Nexus is an AI-powered platform that transforms natural language descriptions into fully functional applications by spawning specialized AI agents that collaborate to design and build projects.

## Architecture

### 1. **Director AI** - The Orchestrator
- Analyzes user intent and transforms it into structured requirements
- Creates comprehensive Task Ledgers containing all project metadata
- Determines which specialized agents are needed
- Builds the Directed Acyclic Graph (DAG) for agent execution
- Coordinates risk assessment and guardrail checking

### 2. **Agent Library** - Specialized Workers
The system includes the following agent roles:

- **Backend Engineer**: API development, microservices, business logic
- **Frontend Engineer**: UI/UX design, responsive interfaces, client-side logic
- **Database Architect**: Schema design, optimization, data strategies
- **Security Engineer**: Compliance, threat assessment, encryption strategies
- **DevOps Engineer**: CI/CD, infrastructure, deployment automation
- **QA Engineer**: Testing strategies, automation, quality assurance
- **Solution Architect**: Overall system design, technology decisions
- **API Designer**: API contracts, specifications, SDK design

### 3. **Task Ledger** - Comprehensive Project Specification
Contains:
- User intent and extracted requirements
- Functional & non-functional requirements
- Technology stack specifications
- Agent specifications and dependencies
- Directed Acyclic Graph (DAG) for execution order
- Design principles and security requirements
- API specifications and database schemas
- Testing strategy and timeline

### 4. **Agent Spawner & Orchestrator**
- Spawns agents based on task ledger specifications
- Manages agent lifecycle
- Coordinates parallel execution respecting dependencies
- Persists agent registry to Cosmos DB
- Publishes coordination events via Azure Service Bus

## Project Structure

```
/home/frozer/Desktop/nexus/
├── main.py                 # Main application with all components
├── .env                    # Configuration file (not in git)
├── requirements.txt        # Python dependencies
└── README.md              # This file
```

## Configuration

All configuration is managed via `.env` file:

```env
# Azure OpenAI
AZURE_OPENAI_ENDPOINT=<your-endpoint>
AZURE_OPENAI_KEY=<your-key>
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_VERSION=2024-05-01-preview

# Cosmos DB
COSMOS_CONNECTION_STR=<your-connection-string>
DATABASE_NAME=agentic-nexus-db
LEDGER_CONTAINER=TaskLedgers
AGENT_CONTAINER=AgentRegistry

# Service Bus
SERVICE_BUS_STR=<your-connection-string>
GHOST_HANDSHAKE_QUEUE=agent-handshake-stubs
AGENT_COORDINATION_TOPIC=agent-coordination-events
AGENT_EXECUTION_QUEUE=agent-execution-queue

# Application
LOG_LEVEL=INFO
MAX_PARALLEL_AGENTS=5
AGENT_TIMEOUT_SECONDS=300
ENVIRONMENT=development
```

## Key Components

### TaskLedger
Comprehensive data structure containing:
- Project metadata (id, owner, collaborators)
- Requirements (functional & non-functional)
- Technology constraints and stack
- Agent specifications with dependencies
- Parallel execution groups
- Design principles and security requirements

### DirectorAI
```python
async def clarify_intent(ledger: TaskLedger) -> Dict
```
- Transforms user intent into structured requirements
- Populates all fields in the task ledger
- Performs risk assessment

```python
async def generate_agent_dag(ledger: TaskLedger) -> Tuple[Dict, List[List[str]]]
```
- Generates dependency graph between agents
- Creates parallel execution groups

### Agent
Base class for all specialized agents:
```python
async def execute(task_context: Dict) -> Dict
```
- Executes agent-specific tasks
- Returns results in JSON format
- Reports status and errors

### AgentRegistry
Contains profiles for all 8 specialized agent types with:
- Role descriptions
- Specialties and capabilities
- System prompts for LLM interactions
- Best practices and guidelines

### AgentSpawner
```python
async def spawn_agents_from_ledger(ledger: TaskLedger) -> Dict[str, Agent]
```
- Creates agent instances based on task ledger
- Manages agent lifecycle

```python
async def execute_agents_with_dag(dag, parallel_groups) -> Dict
```
- Executes agents respecting dependencies
- Runs independent agents in parallel
- Collects and aggregates results

## Execution Flow

1. **Intent Capture**: User provides natural language description
2. **Analysis**: Director AI analyzes and creates comprehensive task ledger
3. **Agent Planning**: Director determines required agents and dependencies
4. **Agent Spawning**: AgentSpawner creates agent instances
5. **DAG Generation**: Dependency graph and parallel groups created
6. **Parallel Execution**: Agents execute respecting dependencies
7. **Result Aggregation**: Results collected from all agents
8. **Persistence**: Task ledger and agent registry saved to Cosmos DB

## Data Persistence

### Cosmos DB Schema

**TaskLedgers Container**:
```json
{
  "id": "project_id",
  "project_id": "...",
  "owner_id": "...",
  "user_intent": "...",
  "functional_requirements": [...],
  "non_functional_requirements": {...},
  "technology_stack": {...},
  "agent_specifications": {...},
  "status": "DRAFT|IN_PROGRESS|COMPLETED",
  ...
}
```

**AgentRegistry Container**:
```json
{
  "id": "agents_project_id",
  "project_id": "...",
  "timestamp": "...",
  "agents": [
    {
      "agent_id": "...",
      "role": "backend_engineer",
      "status": "COMPLETED",
      "outputs": {...}
    }
  ],
  "total_agents": 5
}
```

## Service Bus Events

### Ghost Handshake
Pre-emptive API stub notification:
```json
{
  "type": "GHOST_HANDSHAKE",
  "source_agent": "BackendEngineer",
  "stub": {
    "endpoint": "/api/documents",
    "methods": ["GET", "POST"],
    "auth": "Bearer JWT"
  },
  "timestamp": "..."
}
```

### Agent Coordination Events
```json
{
  "event_type": "AGENT_READY|AGENT_COMPLETED|AGENT_FAILED",
  "data": {...},
  "timestamp": "..."
}
```

## Usage

### Installation

```bash
cd /home/frozer/Desktop/nexus
pip install -r requirements.txt
```

### Running the Application

```bash
python main.py
```

### Example Output

```
🚀 Initializing Agentic Nexus Platform...
🧠 Director AI analyzing requirements...
📋 Task Ledger populated with 5 agent specifications
👥 Spawning specialized agents...
✨ backend_engineer_0_abc123: backend_engineer (Status: CREATED)
✨ frontend_engineer_0_def456: frontend_engineer (Status: CREATED)
...
📊 Building agent dependency graph...
⚙️  Starting agent execution phase...
🔄 Executing parallel group: ['backend_engineer_0_abc123', 'database_architect_0_ghi789']
🔄 Agent backend_engineer_0_abc123 executing task...
✅ Agent backend_engineer_0_abc123 completed successfully
...
✅ AGENTIC NEXUS SETUP COMPLETE
Project ID: a1b2c3d4
Agents Spawned: 5
Parallel Execution Groups: 3
```

## Advanced Features

### Risk Assessment & Guardrails
Director AI flags high-risk technical decisions:
- High-cost Azure services
- Security anti-patterns
- Scalability concerns
- Compliance violations

### Parallel Execution
- Agents execute in parallel respecting DAG dependencies
- Independent agents run simultaneously
- Results aggregated for dependent agents

### Extensibility
Add new agent types by:
1. Define new `AgentRole` in `AgentRole` enum
2. Create profile in `AgentRegistry.AGENT_PROFILES`
3. System automatically spawns and coordinates

## Monitoring & Logging

All operations logged with structured format:
- Agent spawning
- Execution flow
- Error handling
- Performance metrics

Set `LOG_LEVEL` in `.env` to control verbosity.

## Future Enhancements

1. **Agent Learning**: Agents learn from past projects
2. **Real-time Coordination**: WebSocket-based agent communication
3. **Custom Agents**: User-defined agent roles
4. **Feedback Loop**: Human feedback integration
5. **Incremental Build**: Progressive generation with checkpoints
6. **Agent Persistence**: Save/restore agent state
7. **Cost Optimization**: Automatic cost monitoring
8. **Performance Tuning**: Agent optimization suggestions

## Security Considerations

- All credentials in `.env` (never commit to git)
- Azure managed identities for authentication
- Cosmos DB encryption at rest
- Service Bus encrypted communication
- OpenAI API key rotation recommended
- RBAC for multi-tenant isolation

## Troubleshooting

### Agent Spawning Issues
- Check Agent roles are defined in `AgentRole` enum
- Verify agent profiles exist in `AgentRegistry`
- Check Cosmos DB connectivity

### DAG Dependency Issues
- Ensure cyclic dependencies don't exist
- Verify all referenced agents are spawned
- Check parallel group definitions

### Execution Failures
- Check Azure OpenAI quota and rate limits
- Verify Service Bus connection strings
- Review agent-specific error logs

## Performance Metrics

- Average agent spawn time: ~500ms
- Average task execution: ~5-10s per agent
- Parallel execution speedup: 2-5x for independent agents
- Cosmos DB throughput: Configured for multi-agent writes

## Support & Contribution

For issues or enhancements:
1. Check logs for detailed error messages
2. Verify Azure service connectivity
3. Review agent-specific documentation
4. Check Service Bus event logs

---

**Version**: 1.0  
**Last Updated**: 2026-03-02  
**Architecture**: Directed Acyclic Graph (DAG) with Parallel Execution
