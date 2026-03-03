# Environment Setup Guide

## Prerequisites

- Python 3.9+
- Azure subscription with the following resources:
  - Azure OpenAI (GPT-4o deployment)
  - Azure Cosmos DB
  - Azure Service Bus
- Git

## Step 1: Clone/Setup Repository

```bash
cd /home/frozer/Desktop/nexus
```

## Step 2: Create Python Virtual Environment (Optional but Recommended)

```bash
# Create virtual environment
python -m venv venv

# Activate it
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

## Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

## Step 4: Configure Azure Resources

### 4.1 Azure OpenAI
1. Go to [Azure Portal](https://portal.azure.com)
2. Create/navigate to Azure OpenAI resource
3. Deploy a GPT-4o model (named `gpt-4o`)
4. Get your:
   - Endpoint URL (format: `https://<resource-name>.openai.azure.com/`)
   - API Key
   - Deployment name

### 4.2 Azure Cosmos DB
1. Create Cosmos DB account (SQL API)
2. Create database: `agentic-nexus-db`
3. Create containers:
   - `TaskLedgers` (partition key: `/owner_id`)
   - `AgentRegistry` (partition key: `/project_id`)
4. Get connection string from "Connection String" page

### 4.3 Azure Service Bus
1. Create Service Bus namespace
2. Create queues:
   - `agent-handshake-stubs`
   - `agent-execution-queue`
3. Create topics:
   - `agent-coordination-events`
4. Get connection string from "Shared access policies"

## Step 5: Create .env File

Create `/home/frozer/Desktop/nexus/.env`:

```env
# ==========================================
# AZURE OPENAI CONFIGURATION
# ==========================================
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_KEY=your_api_key_here
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_VERSION=2024-05-01-preview

# ==========================================
# AZURE COSMOS DB CONFIGURATION
# ==========================================
COSMOS_CONNECTION_STR=AccountEndpoint=https://your-cosmos.documents.azure.com:443/;AccountKey=your_key_here;
DATABASE_NAME=agentic-nexus-db
LEDGER_CONTAINER=TaskLedgers
AGENT_CONTAINER=AgentRegistry

# ==========================================
# AZURE SERVICE BUS CONFIGURATION
# ==========================================
SERVICE_BUS_STR=Endpoint=sb://your-namespace.servicebus.windows.net/;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=your_key_here
GHOST_HANDSHAKE_QUEUE=agent-handshake-stubs
AGENT_COORDINATION_TOPIC=agent-coordination-events
AGENT_EXECUTION_QUEUE=agent-execution-queue

# ==========================================
# APPLICATION CONFIGURATION
# ==========================================
LOG_LEVEL=INFO
MAX_PARALLEL_AGENTS=5
AGENT_TIMEOUT_SECONDS=300
ENVIRONMENT=development
```

## Step 6: Verify Setup

```bash
# Test imports
python -c "import asyncio; import azure.cosmos; import azure.servicebus; from openai import AzureOpenAI; print('✅ All imports successful')"

# Check syntax
python -m py_compile main.py && echo "✅ Syntax valid"

# Check environment variables
python -c "from dotenv import load_dotenv; import os; load_dotenv(); print(f'Azure OpenAI: {os.getenv(\"AZURE_OPENAI_ENDPOINT\")}')"
```

## Step 7: Run the Application

```bash
python main.py
```

### Expected Output

```
🚀 Initializing Agentic Nexus Platform...
🧠 Director AI analyzing requirements...
📋 Task Ledger populated with X agent specifications
👥 Spawning specialized agents...
✨ Agent spawned: backend_engineer_0_abc123 (backend_engineer)
...
✅ AGENTIC NEXUS SETUP COMPLETE
Project ID: a1b2c3d4
Agents Spawned: 5
...
```

## Troubleshooting

### Import Errors

```bash
# Reinstall dependencies
pip install --upgrade -r requirements.txt
```

### Azure Connectivity Issues

1. **Verify credentials** in `.env`
2. **Check firewall rules** - Cosmos DB/Service Bus may need IP allowlisting
3. **Test connection**:
   ```bash
   python -c "from azure.cosmos import CosmosClient; from dotenv import load_dotenv; import os; load_dotenv(); client = CosmosClient.from_connection_string(os.getenv('COSMOS_CONNECTION_STR')); print('✅ Cosmos connected')"
   ```

### OpenAI API Issues

1. **Check quota**: Ensure sufficient quota in Azure OpenAI
2. **Verify deployment**: Model must be named exactly `gpt-4o`
3. **Test API**:
   ```bash
   python -c "from openai import AzureOpenAI; from dotenv import load_dotenv; import os; load_dotenv(); client = AzureOpenAI(api_key=os.getenv('AZURE_OPENAI_KEY'), azure_endpoint=os.getenv('AZURE_OPENAI_ENDPOINT')); print('✅ OpenAI connected')"
   ```

### Service Bus Issues

1. **Check queue existence**: Verify all queues are created
2. **Check access policies**: RootManageSharedAccessKey should have Send/Listen permissions
3. **Test connection**:
   ```bash
   python -c "import asyncio; from azure.servicebus.aio import ServiceBusClient; from dotenv import load_dotenv; import os; load_dotenv(); asyncio.run(ServiceBusClient.from_connection_string(os.getenv('SERVICE_BUS_STR')).close()); print('✅ Service Bus connected')"
   ```

## Development Workflow

### 1. Local Testing

```bash
python main.py
```

### 2. Debugging

Enable debug logging:

```env
LOG_LEVEL=DEBUG
```

### 3. Running Tests (when added)

```bash
pytest tests/ -v --cov=.
```

## Performance Tuning

### Increase Parallelism

```env
MAX_PARALLEL_AGENTS=10  # Default: 5
```

### Increase Timeouts

```env
AGENT_TIMEOUT_SECONDS=600  # Default: 300
```

### Azure Resource Scaling

**Cosmos DB**:
- Start with 400 RU/s
- Monitor consumption
- Scale based on traffic

**Service Bus**:
- Standard tier supports sufficient throughput
- Enable auto-scaling if available

## Security Checklist

- [ ] Never commit `.env` to git (already in .gitignore pattern)
- [ ] Rotate API keys regularly
- [ ] Use managed identities when possible
- [ ] Enable network isolation for databases
- [ ] Enable audit logging
- [ ] Review IAM permissions

## Monitoring

### Application Logs

Logs are output to console with LOG_LEVEL format:
- `DEBUG`: Detailed trace information
- `INFO`: General informational messages
- `WARNING`: Warning messages
- `ERROR`: Error messages

### Azure Monitoring

1. **Application Insights**: Monitor application performance
2. **Cosmos DB Metrics**: Track database operations and costs
3. **Service Bus Metrics**: Monitor queue/topic operations

## Next Steps

1. Customize user input in `main()` function
2. Add more specialized agents as needed
3. Implement result processing and artifact generation
4. Add web API layer for production deployment
5. Implement agent result persistence and retrieval

## Support

For issues:
1. Check logs with `LOG_LEVEL=DEBUG`
2. Verify Azure resource connectivity
3. Review [Agent Library Documentation](./AGENT_LIBRARY.md)
4. Check [README](./README.md) for architecture details

---

**Setup Guide Version**: 1.0  
**Last Updated**: 2026-03-02
