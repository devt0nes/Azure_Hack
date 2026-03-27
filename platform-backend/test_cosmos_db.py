"""
Comprehensive Cosmos DB Connection and Integration Tests
Tests connection, container creation, CRUD operations, and agent library integration
"""

import pytest

pytest.skip("Superseded by test_cosmos_db_startup.py", allow_module_level=True)

import os
import sys
import json
import logging
from datetime import datetime
from typing import Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TestCosmosDBConnection:
    """Tests for Cosmos DB connection"""

    @pytest.fixture
    def cosmos_client(self):
        """Create a Cosmos DB client for testing"""
        from cosmos_client import CosmosDBClient
        client = CosmosDBClient()
        yield client
        # Cleanup would go here

    def test_client_initialization(self):
        """Test that CosmosDB client initializes correctly"""
        from cosmos_client import CosmosDBClient
        
        # Should raise error if COSMOS_CONNECTION_STR is not set
        if not os.getenv("COSMOS_CONNECTION_STR"):
            with pytest.raises(ValueError):
                CosmosDBClient()
            logger.info("✓ Client initialization validation works (missing connection string)")
        else:
            client = CosmosDBClient()
            assert client.db_name is not None
            assert client.connection_string is not None
            logger.info("✓ Client initialized with connection string")

    def test_connection(self, cosmos_client):
        """Test Cosmos DB connection"""
        if not os.getenv("COSMOS_CONNECTION_STR"):
            logger.warning("⚠ COSMOS_CONNECTION_STR not set, skipping connection test")
            pytest.skip("COSMOS_CONNECTION_STR not configured")
        
        result = cosmos_client.connect()
        assert result is True, "Failed to connect to Cosmos DB"
        assert cosmos_client.is_connected(), "Client should be connected"
        logger.info("✓ Successfully connected to Cosmos DB")

    def test_health_check(self, cosmos_client):
        """Test health check functionality"""
        if not os.getenv("COSMOS_CONNECTION_STR"):
            pytest.skip("COSMOS_CONNECTION_STR not configured")
        
        cosmos_client.connect()
        health = cosmos_client.health_check()
        
        assert "connected" in health
        assert "database" in health
        assert "containers" in health
        logger.info(f"✓ Health check successful: {json.dumps(health, indent=2)}")


class TestCosmosDBContainerCreation:
    """Tests for container creation and management"""

    @pytest.fixture
    def connected_client(self):
        """Create and connect a Cosmos DB client"""
        from cosmos_client import CosmosDBClient
        client = CosmosDBClient()
        
        if os.getenv("COSMOS_CONNECTION_STR"):
            if client.connect():
                yield client
            else:
                pytest.skip("Could not connect to Cosmos DB")
        else:
            pytest.skip("COSMOS_CONNECTION_STR not configured")

    def test_create_single_container(self, connected_client):
        """Test creating a single container"""
        container_name = "TestContainer"
        success = connected_client.create_container(
            container_name=container_name,
            partition_key="/id",
            throughput=400
        )
        assert success is True, f"Failed to create container {container_name}"
        logger.info(f"✓ Created container: {container_name}")

    def test_create_container_idempotent(self, connected_client):
        """Test that creating a container twice is idempotent"""
        container_name = "TestContainer"
        
        # First creation
        success1 = connected_client.create_container(container_name)
        assert success1 is True
        
        # Second creation (should not fail)
        success2 = connected_client.create_container(container_name)
        assert success2 is True
        logger.info("✓ Container creation is idempotent")

    def test_ensure_all_containers(self, connected_client):
        """Test ensuring all required containers exist"""
        results = connected_client.ensure_containers()
        
        assert isinstance(results, dict)
        assert len(results) > 0
        
        # Check that at least the main containers were attempted
        for container_name, success in results.items():
            logger.info(f"  Container '{container_name}': {'✓' if success else '✗'}")
            assert success is True, f"Failed to ensure container {container_name}"
        
        logger.info("✓ All required containers ensured successfully")

    def test_list_containers(self, connected_client):
        """Test listing containers in the database"""
        containers = connected_client.list_containers()
        
        assert isinstance(containers, list)
        logger.info(f"✓ Found {len(containers)} containers: {containers}")


class TestCosmosDBCRUDOperations:
    """Tests for CRUD operations"""

    @pytest.fixture
    def connected_client(self):
        """Create and connect a Cosmos DB client"""
        from cosmos_client import CosmosDBClient
        client = CosmosDBClient()
        
        if os.getenv("COSMOS_CONNECTION_STR"):
            if client.connect():
                client.create_container("TestContainer")
                yield client
            else:
                pytest.skip("Could not connect to Cosmos DB")
        else:
            pytest.skip("COSMOS_CONNECTION_STR not configured")

    def test_insert_document(self, connected_client):
        """Test inserting a document"""
        doc = {
            "id": f"test-doc-{datetime.now().timestamp()}",
            "name": "Test Document",
            "type": "test",
            "data": {"key": "value"}
        }
        
        result = connected_client.insert_document("TestContainer", doc)
        assert result is not None
        assert result["id"] == doc["id"]
        logger.info(f"✓ Inserted document: {doc['id']}")

    def test_get_document(self, connected_client):
        """Test retrieving a document"""
        doc_id = f"test-doc-{datetime.now().timestamp()}"
        doc = {
            "id": doc_id,
            "name": "Test Get",
            "type": "test"
        }
        
        # Insert first
        connected_client.insert_document("TestContainer", doc)
        
        # Now retrieve
        retrieved = connected_client.get_document("TestContainer", doc_id)
        assert retrieved is not None
        assert retrieved["id"] == doc_id
        assert retrieved["name"] == "Test Get"
        logger.info(f"✓ Retrieved document: {doc_id}")

    def test_update_document(self, connected_client):
        """Test updating a document"""
        doc_id = f"test-update-{datetime.now().timestamp()}"
        doc = {
            "id": doc_id,
            "name": "Original",
            "status": "active"
        }
        
        # Insert
        connected_client.insert_document("TestContainer", doc)
        
        # Update
        result = connected_client.update_document(
            "TestContainer",
            doc_id,
            {"name": "Updated", "status": "inactive"}
        )
        
        assert result is not None
        assert result["name"] == "Updated"
        assert result["status"] == "inactive"
        logger.info(f"✓ Updated document: {doc_id}")

    def test_delete_document(self, connected_client):
        """Test deleting a document"""
        doc_id = f"test-delete-{datetime.now().timestamp()}"
        doc = {
            "id": doc_id,
            "name": "To Delete"
        }
        
        # Insert
        connected_client.insert_document("TestContainer", doc)
        
        # Delete
        success = connected_client.delete_document("TestContainer", doc_id)
        assert success is True
        
        # Verify it's gone
        retrieved = connected_client.get_document("TestContainer", doc_id)
        assert retrieved is None
        logger.info(f"✓ Deleted document: {doc_id}")

    def test_query_documents(self, connected_client):
        """Test querying documents"""
        # Insert test documents
        for i in range(3):
            doc = {
                "id": f"query-test-{i}-{datetime.now().timestamp()}",
                "name": f"Query Test {i}",
                "type": "query"
            }
            connected_client.insert_document("TestContainer", doc)
        
        # Query
        results = connected_client.query_documents(
            "TestContainer",
            "SELECT * FROM c WHERE c.type = @type",
            [{"name": "@type", "value": "query"}]
        )
        
        assert len(results) >= 3
        logger.info(f"✓ Queried {len(results)} documents")


class TestCosmosDBAgentIntegration:
    """Tests for agent library integration with Cosmos DB"""

    @pytest.fixture
    def connected_client(self):
        """Create and connect a Cosmos DB client"""
        from cosmos_client import CosmosDBClient
        client = CosmosDBClient()
        
        if os.getenv("COSMOS_CONNECTION_STR"):
            if client.connect():
                client.ensure_containers()
                yield client
            else:
                pytest.skip("Could not connect to Cosmos DB")
        else:
            pytest.skip("COSMOS_CONNECTION_STR not configured")

    def test_agent_registry_container(self, connected_client):
        """Test AgentRegistry container for storing agent metadata"""
        agent_container = os.getenv("AGENT_CONTAINER", "AgentRegistry")
        
        agent_doc = {
            "agent_id": "backend_engineer_001",
            "name": "Backend Engineer",
            "version": "1.0.0",
            "role": "API Development",
            "status": "active",
            "created_at": datetime.now().isoformat()
        }
        
        result = connected_client.insert_document(agent_container, agent_doc)
        assert result is not None
        logger.info(f"✓ Stored agent in {agent_container}")

    def test_task_ledger_container(self, connected_client):
        """Test TaskLedger container for storing task execution logs"""
        ledger_container = os.getenv("LEDGER_CONTAINER", "TaskLedgers")
        
        task_doc = {
            "task_id": f"task_{datetime.now().timestamp()}",
            "project_id": "project_123",
            "agent_id": "backend_engineer_001",
            "status": "in_progress",
            "phase": "implementation",
            "created_at": datetime.now().isoformat()
        }
        
        result = connected_client.insert_document(ledger_container, task_doc)
        assert result is not None
        logger.info(f"✓ Stored task ledger in {ledger_container}")

    def test_template_library_container(self, connected_client):
        """Test TemplateLibrary container for storing agent code templates"""
        template_container = os.getenv("COSMOS_TEMPLATE_CONTAINTER", "TemplateLibrary")
        
        template_doc = {
            "template_id": "express_api_template",
            "type": "api",
            "language": "javascript",
            "framework": "express",
            "version": "1.0.0",
            "content": {
                "app_js": "// Express app template",
                "routes_example": "// Route example"
            }
        }
        
        result = connected_client.insert_document(template_container, template_doc)
        assert result is not None
        logger.info(f"✓ Stored template in {template_container}")

    def test_agent_workflow_simulation(self, connected_client):
        """Test a simulated agent workflow with Cosmos DB"""
        agent_container = os.getenv("AGENT_CONTAINER", "AgentRegistry")
        ledger_container = os.getenv("LEDGER_CONTAINER", "TaskLedgers")
        
        # Create agent
        agent = {
            "agent_id": "test_agent_workflow",
            "name": "Workflow Test Agent",
            "status": "active"
        }
        connected_client.insert_document(agent_container, agent)
        
        # Create task
        task = {
            "task_id": f"workflow_task_{datetime.now().timestamp()}",
            "agent_id": "test_agent_workflow",
            "status": "created"
        }
        connected_client.insert_document(ledger_container, task)
        
        # Retrieve and verify
        retrieved_agent = connected_client.get_document(
            agent_container,
            agent["agent_id"]
        )
        retrieved_task = connected_client.get_document(
            ledger_container,
            task["task_id"]
        )
        
        assert retrieved_agent is not None
        assert retrieved_task is not None
        logger.info("✓ Agent workflow simulation successful")


class TestCosmosDBErrorHandling:
    """Tests for error handling and edge cases"""

    @pytest.fixture
    def connected_client(self):
        """Create and connect a Cosmos DB client"""
        from cosmos_client import CosmosDBClient
        client = CosmosDBClient()
        
        if os.getenv("COSMOS_CONNECTION_STR"):
            if client.connect():
                client.create_container("TestContainer")
                yield client
            else:
                pytest.skip("Could not connect to Cosmos DB")
        else:
            pytest.skip("COSMOS_CONNECTION_STR not configured")

    def test_get_nonexistent_document(self, connected_client):
        """Test getting a document that doesn't exist"""
        result = connected_client.get_document(
            "TestContainer",
            "nonexistent_doc_123456"
        )
        assert result is None
        logger.info("✓ Correctly handled nonexistent document")

    def test_delete_nonexistent_document(self, connected_client):
        """Test deleting a document that doesn't exist"""
        result = connected_client.delete_document(
            "TestContainer",
            "nonexistent_doc_123456"
        )
        # Should not fail (idempotent)
        assert result is True
        logger.info("✓ Correctly handled deletion of nonexistent document")

    def test_query_empty_results(self, connected_client):
        """Test querying with no results"""
        results = connected_client.query_documents(
            "TestContainer",
            "SELECT * FROM c WHERE c.nonexistent = @val",
            [{"name": "@val", "value": "nothing"}]
        )
        assert isinstance(results, list)
        assert len(results) == 0
        logger.info("✓ Correctly handled empty query results")


def test_singleton_pattern():
    """Test the singleton pattern for Cosmos DB client"""
    if not os.getenv("COSMOS_CONNECTION_STR"):
        pytest.skip("COSMOS_CONNECTION_STR not configured")
    
    from cosmos_client import get_cosmos_client, init_cosmos_db
    
    client1 = get_cosmos_client()
    client2 = get_cosmos_client()
    
    assert client1 is client2
    logger.info("✓ Singleton pattern works correctly")


def test_full_initialization():
    """Test full initialization of Cosmos DB"""
    if not os.getenv("COSMOS_CONNECTION_STR"):
        pytest.skip("COSMOS_CONNECTION_STR not configured")
    
    from cosmos_client import init_cosmos_db
    
    success = init_cosmos_db()
    assert success is True
    logger.info("✓ Full Cosmos DB initialization successful")


# Manual test runner for debugging
if __name__ == "__main__":
    print("\n" + "="*60)
    print("COSMOS DB CONNECTION & INTEGRATION TESTS")
    print("="*60 + "\n")

    # Check environment
    print("Environment Check:")
    print(f"  COSMOS_CONNECTION_STR: {'✓ Set' if os.getenv('COSMOS_CONNECTION_STR') else '✗ Not set'}")
    print(f"  COSMOS_DB_NAME: {os.getenv('COSMOS_DB_NAME', 'agentic-nexus-db')}")
    print(f"  LEDGER_CONTAINER: {os.getenv('LEDGER_CONTAINER', 'TaskLedgers')}")
    print(f"  AGENT_CONTAINER: {os.getenv('AGENT_CONTAINER', 'AgentRegistry')}")
    print()

    # Run with pytest if available
    exit_code = pytest.main([
        __file__,
        "-v",
        "--tb=short",
        "-s"  # Show output
    ])

    sys.exit(exit_code)
