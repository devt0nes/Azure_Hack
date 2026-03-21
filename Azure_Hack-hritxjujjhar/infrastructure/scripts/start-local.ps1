# Day 4: Quick start script for local development with Docker Compose
# Starts both frontend and backend with hot-reload

Write-Host "🚀 Starting Platform A local environment..." -ForegroundColor Cyan
Write-Host ""

# Check if Docker is running
$dockerRunning = docker ps 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Docker is not running. Please start Docker Desktop." -ForegroundColor Red
    exit 1
}

# Navigate to infrastructure directory
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location "$scriptPath/.."

Write-Host "📦 Starting services with Docker Compose..." -ForegroundColor Yellow
Write-Host "   - Frontend: http://localhost:5173" -ForegroundColor Gray
Write-Host "   - Backend:  http://localhost:8000" -ForegroundColor Gray
Write-Host ""

# Start Docker Compose
docker-compose -f infrastructure/docker-compose.template.yml up --build

# Cleanup on exit
Write-Host "`n🛑 Shutting down services..." -ForegroundColor Yellow
docker-compose -f infrastructure/docker-compose.template.yml down
