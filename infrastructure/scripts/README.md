# Infrastructure Scripts

Day 4 automation scripts for local development and deployment.

## Local Development

### `start-local.ps1`
Quick start for Docker Compose environment with hot-reload.

```powershell
.\start-local.ps1
```

**What it does:**
- Checks if Docker daemon is running
- Starts frontend (localhost:5173) and backend (localhost:8000)
- Enables hot-reload on both services
- Gracefully shuts down on Ctrl+C

**Requirements:**
- Docker Desktop installed and running
- `.env` file configured in frontend directory

---

### `start-devtunnel.ps1`
Creates Azure Dev Tunnel for public preview access.

```powershell
.\start-devtunnel.ps1 -Port 5173 -TunnelName "platform-preview"
```

**Parameters:**
- `-Port`: Local port to forward (default: 5173)
- `-TunnelName`: Tunnel identifier (default: "platform-preview")

**What it does:**
- Creates persistent dev tunnel if doesn't exist
- Connects to existing tunnel if already created
- Exposes localhost via public HTTPS URL (`https://*.devtunnels.ms`)
- Saves tunnel URL to `.tunnel-url` file (read by backend API)
- Keeps tunnel alive until Ctrl+C

**Requirements:**
- Azure Dev Tunnels CLI: `winget install Microsoft.devtunnel`
- Azure account (free tier works)

**Output:**
```
Tunnel active!
Public URL: https://abc123-5173.devtunnels.ms
Forwarding to: http://localhost:5173
```

---

### `stop-devtunnel.ps1`
Stops and removes active dev tunnel.

```powershell
.\stop-devtunnel.ps1 -TunnelName "platform-preview"
```

**What it does:**
- Finds tunnel by name
- Deletes tunnel from Azure
- Cleans up `.tunnel-url` file

---

## Azure Deployment

### `setup-azure.sh`
*Placeholder for Azure resource provisioning (Day 5+)*

Will provision:
- App Service (frontend + backend)
- Cosmos DB account
- SignalR Service
- Event Grid topics
- Application Insights

---

## Usage Examples

### Standard local development
```powershell
# Terminal 1: Start Docker Compose
.\start-local.ps1

# Open browser: http://localhost:5173
```

### With public tunnel (for sharing/testing)
```powershell
# Terminal 1: Start Docker Compose
.\start-local.ps1

# Terminal 2: Start dev tunnel
.\start-devtunnel.ps1

# Share tunnel URL from Terminal 2 output
```

### Cleanup
```powershell
# Stop Docker Compose (Ctrl+C in Terminal 1)
# Stop dev tunnel (Ctrl+C in Terminal 2)

# Or manually:
.\stop-devtunnel.ps1
docker-compose -f ../docker-compose.template.yml down
```

---

## Troubleshooting

**Docker not starting:**
- Ensure Docker Desktop is installed and running
- Check Docker daemon status: `docker ps`

**Dev tunnel not working:**
- Install CLI: `winget install Microsoft.devtunnel`
- Login to Azure: `devtunnel user login`
- Check existing tunnels: `devtunnel list`

**Hot-reload not working:**
- Check volume mounts in `docker-compose.template.yml`
- Ensure files are saved (not just modified)
- Restart containers: `docker-compose restart`

**Port conflicts:**
- Frontend (5173): Change in `docker-compose.template.yml` ports
- Backend (8000): Change in `docker-compose.template.yml` ports
- Update `.env` files accordingly
