#!/bin/bash

# Agentic Nexus - Integration Test Script
# Verifies all components are working correctly

echo "🔍 Agentic Nexus Integration Test"
echo "=================================="
echo ""

# Test 1: Backend is running
echo "1️⃣  Testing Backend Health..."
HEALTH=$(curl -s http://localhost:8000/api/health)
if echo "$HEALTH" | grep -q "healthy"; then
    echo "✅ Backend is healthy"
else
    echo "❌ Backend health check failed"
    echo "   Make sure to run: cd tentative-backend && uvicorn app:app --reload --port 8000"
    exit 1
fi

echo ""

# Test 2: Frontend is accessible
echo "2️⃣  Testing Frontend..."
if curl -s http://localhost:5173 | grep -q "React"; then
    echo "✅ Frontend is running"
else
    echo "❌ Frontend not accessible"
    echo "   Make sure to run: cd platform-frontend && npm run dev"
    exit 1
fi

echo ""

# Test 3: Projects endpoint
echo "3️⃣  Testing Projects Endpoint..."
PROJECTS=$(curl -s http://localhost:8000/api/projects)
if echo "$PROJECTS" | grep -q "projects"; then
    echo "✅ Projects endpoint working"
else
    echo "❌ Projects endpoint failed"
    exit 1
fi

echo ""

# Test 4: Database persistence
echo "4️⃣  Testing Database Persistence..."
if [ -f "tentative-backend/projects_db.json" ]; then
    echo "✅ Database file exists"
    PROJECT_COUNT=$(cat tentative-backend/projects_db.json | grep -o "project_id" | wc -l)
    echo "   Current projects: $PROJECT_COUNT"
else
    echo "❌ Database file not found"
    exit 1
fi

echo ""

# Test 5: Simulate clarify endpoint
echo "5️⃣  Testing /clarify Endpoint..."
RESULT=$(curl -s -X POST http://localhost:8000/clarify \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "test-integration-'$(date +%s)'",
    "user_input": "Test project creation"
  }')

if echo "$RESULT" | grep -q "project_id"; then
    echo "✅ /clarify endpoint working"
    PROJECT_ID=$(echo "$RESULT" | grep -o '"project_id":"[^"]*' | head -1 | cut -d'"' -f4)
    echo "   Created project: $PROJECT_ID"
else
    echo "❌ /clarify endpoint failed"
    exit 1
fi

echo ""

# Test 6: AEG endpoint
if [ ! -z "$PROJECT_ID" ]; then
    echo "6️⃣  Testing /aeg Endpoint..."
    AEG=$(curl -s "http://localhost:8000/aeg?project_id=$PROJECT_ID")
    if echo "$AEG" | grep -q "agent_specifications"; then
        echo "✅ /aeg endpoint working"
    else
        echo "❌ /aeg endpoint failed"
        exit 1
    fi
else
    echo "6️⃣  Skipping /aeg test (no project created)"
fi

echo ""
echo "=================================="
echo "✅ All integration tests passed!"
echo ""
echo "🚀 Your system is ready to use:"
echo "   Frontend: http://localhost:5173"
echo "   Backend:  http://localhost:8000"
echo "   Docs:     http://localhost:8000/api/docs"
echo ""
echo "📝 Next steps:"
echo "   1. Open http://localhost:5173 in your browser"
echo "   2. Describe your project in the Conversation page"
echo "   3. Watch the code generation in real-time"
echo "   4. View the agent execution graph in AEGView"
