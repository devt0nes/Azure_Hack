#!/usr/bin/env python3
"""
Quick Cosmos DB Verification Script
Verifies connection, container creation, and basic operations
"""

import os
import sys
import json
from datetime import datetime

# Load environment variables from .env
from dotenv import load_dotenv
load_dotenv()

print("\n" + "="*70)
print("COSMOS DB VERIFICATION & DIAGNOSIS")
print("="*70 + "\n")

all_checks_passed = True

# Check environment
print("1. ENVIRONMENT CHECK")
print("-" * 70)
cosmos_conn = os.getenv("COSMOS_CONNECTION_STR")
db_name = os.getenv("COSMOS_DB_NAME", "agentic-nexus-db")
ledger_container = os.getenv("LEDGER_CONTAINER", "TaskLedgers")
agent_container = os.getenv("AGENT_CONTAINER", "AgentRegistry")
template_container = os.getenv("COSMOS_TEMPLATE_CONTAINTER", "TemplateLibrary")

print(f"✓ COSMOS_CONNECTION_STR: {cosmos_conn[:50]}..." if cosmos_conn else "✗ COSMOS_CONNECTION_STR: NOT SET")
print(f"✓ COSMOS_DB_NAME: {db_name}")
print(f"✓ LEDGER_CONTAINER: {ledger_container}")
print(f"✓ AGENT_CONTAINER: {agent_container}")
print(f"✓ TEMPLATE_CONTAINER: {template_container}")
print()

# Try to connect
print("2. CONNECTION TEST")
print("-" * 70)
try:
    from cosmos_client import CosmosDBClient
    
    client = CosmosDBClient()
    print("✓ CosmosDBClient initialized")
    
    if not client.connect():
        print("✗ Failed to connect to Cosmos DB")
        sys.exit(1)
    
    print("✓ Connected to Cosmos DB")
    print(f"✓ Database: {db_name}")
    print()
    
    # Check health
    print("3. HEALTH CHECK")
    print("-" * 70)
    health = client.health_check()
    print(json.dumps(health, indent=2))
    print()
    
    # List containers
    print("4. CONTAINER STATUS")
    print("-" * 70)
    containers = client.list_containers()
    if containers:
        for container in containers:
            print(f"  ✓ {container}")
    else:
        print("  No containers found")
    print()
    
    # Ensure all required containers
    print("5. CONTAINER CREATION")
    print("-" * 70)
    results = client.ensure_containers()
    for container_name, success in results.items():
        status = "✓" if success else "✗"
        print(f"  {status} {container_name}")
        if not success:
            all_checks_passed = False
    print()
    
    # Test CRUD operations
    print("6. CRUD OPERATIONS TEST")
    print("-" * 70)
    
    # Insert test document
    test_doc = {
        "id": f"test_{datetime.now().timestamp()}",
        "name": "Test Document",
        "timestamp": datetime.now().isoformat()
    }
    
    result = client.insert_document(agent_container, test_doc)
    if result:
        print(f"  ✓ Insert: {test_doc['id']}")
    else:
        print(f"  ✗ Insert failed")
        all_checks_passed = False
    
    # Query documents
    results = client.query_documents(agent_container, "SELECT TOP 5 * FROM c")
    print(f"  ✓ Query: Found {len(results)} documents in {agent_container}")
    
    # Get document
    retrieved = client.get_document(agent_container, test_doc["id"])
    if retrieved:
        print(f"  ✓ Get: Retrieved document {test_doc['id']}")
    else:
        print(f"  ✗ Get failed")
        all_checks_passed = False
    
    # Update document
    updated = client.update_document(
        agent_container,
        test_doc["id"],
        {"name": "Updated Test"}
    )
    if updated:
        print(f"  ✓ Update: Updated document {test_doc['id']}")
    else:
        print(f"  ✗ Update failed")
        all_checks_passed = False
    
    # Delete document
    deleted = client.delete_document(agent_container, test_doc["id"])
    if deleted:
        print(f"  ✓ Delete: Deleted document {test_doc['id']}")
    else:
        print(f"  ✗ Delete failed")
        all_checks_passed = False
    
    print()
    if all_checks_passed:
        print("="*70)
        print("✓ ALL TESTS PASSED!")
        print("="*70 + "\n")
    else:
        print("="*70)
        print("✗ SOME CHECKS FAILED")
        print("="*70 + "\n")
        sys.exit(1)
    
except Exception as e:
    print(f"✗ ERROR: {str(e)}", file=sys.stderr)
    import traceback
    traceback.print_exc()
    sys.exit(1)
