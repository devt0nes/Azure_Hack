#!/bin/bash
# Agentic Nexus Backend - Local Development Startup Script

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}"
echo "╔════════════════════════════════════════════════════════════╗"
echo "║     🚀 Agentic Nexus Backend - Development Environment     ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check Python version
echo -e "${YELLOW}[1/5] Checking Python version...${NC}"
python_version=$(python3 --version 2>&1 | grep -oP '\d+\.\d+')
if (( $(echo "$python_version < 3.11" | bc -l) )); then
    echo -e "${RED}❌ Python 3.11+ required, found $python_version${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python $python_version${NC}"

# Check virtual environment
echo -e "${YELLOW}[2/5] Checking virtual environment...${NC}"
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi
source venv/bin/activate
echo -e "${GREEN}✓ Virtual environment activated${NC}"

# Install dependencies
echo -e "${YELLOW}[3/5] Installing dependencies...${NC}"
pip install --upgrade pip > /dev/null 2>&1
pip install -q -r requirements.txt
echo -e "${GREEN}✓ Dependencies installed${NC}"

# Check .env file
echo -e "${YELLOW}[4/5] Checking environment configuration...${NC}"
if [ ! -f ".env" ]; then
    echo -e "${RED}❌ .env file not found${NC}"
    echo -e "${YELLOW}Please copy .env.example to .env and fill in your credentials:${NC}"
    echo "  cp .env.example .env"
    echo "  # Edit .env with your Azure credentials"
    exit 1
fi
echo -e "${GREEN}✓ .env file found${NC}"

# Verify Azure credentials
echo -e "${YELLOW}[5/5] Verifying Azure credentials...${NC}"
if grep -q "AZURE_OPENAI_KEY=<your-key>" .env; then
    echo -e "${RED}❌ Azure credentials not configured${NC}"
    echo "Please edit .env and fill in your Azure OpenAI credentials"
    exit 1
fi
echo -e "${GREEN}✓ Azure credentials configured${NC}"

echo -e "${GREEN}"
echo "╔════════════════════════════════════════════════════════════╗"
echo "║              ✅ Environment Ready for Development           ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

echo ""
echo -e "${YELLOW}Starting FastAPI development server...${NC}"
echo ""
echo "📚 API Documentation: http://localhost:8000/api/docs"
echo "🔧 OpenAPI Schema: http://localhost:8000/api/openapi.json"
echo "🏥 Health Check: http://localhost:8000/api/health"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop the server${NC}"
echo ""

# Start FastAPI
uvicorn app:app --reload --host 0.0.0.0 --port 8000 --log-level info
