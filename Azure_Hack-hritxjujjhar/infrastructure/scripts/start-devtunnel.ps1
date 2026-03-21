# Day 4: Azure Dev Tunnels startup script
# Creates a persistent tunnel for local preview access

param(
    [Parameter(Mandatory=$false)]
    [int]$Port = 5173,
    
    [Parameter(Mandatory=$false)]
    [string]$TunnelName = "platform-preview"
)

Write-Host "🚇 Starting Azure Dev Tunnel..." -ForegroundColor Cyan

# Check if devtunnel CLI is installed
if (-not (Get-Command devtunnel -ErrorAction SilentlyContinue)) {
    Write-Host "❌ devtunnel CLI not found." -ForegroundColor Red
    Write-Host "Install with: winget install Microsoft.devtunnel" -ForegroundColor Yellow
    exit 1
}

# Check if tunnel already exists
$existingTunnel = devtunnel list 2>&1 | Select-String -Pattern $TunnelName

if ($existingTunnel) {
    Write-Host "✅ Tunnel '$TunnelName' already exists. Connecting..." -ForegroundColor Green
    
    # Get tunnel ID
    $tunnelId = (devtunnel list --output json | ConvertFrom-Json | Where-Object { $_.tunnelName -eq $TunnelName }).tunnelId
    
    if ($tunnelId) {
        # Start the existing tunnel
        devtunnel port create $tunnelId -p $Port --protocol https
        $tunnelUrl = devtunnel host $tunnelId 2>&1 | Select-String -Pattern "https://.*\.devtunnels\.ms" | ForEach-Object { $_.Matches.Value }
    }
} else {
    Write-Host "🆕 Creating new tunnel '$TunnelName'..." -ForegroundColor Yellow
    
    # Create new persistent tunnel
    $createOutput = devtunnel create $TunnelName --allow-anonymous 2>&1
    $tunnelId = $createOutput | Select-String -Pattern "Tunnel ID: ([\w-]+)" | ForEach-Object { $_.Matches.Groups[1].Value }
    
    if ($tunnelId) {
        # Create port mapping
        devtunnel port create $tunnelId -p $Port --protocol https
        
        # Start tunnel and extract URL
        $hostOutput = devtunnel host $tunnelId 2>&1
        $tunnelUrl = $hostOutput | Select-String -Pattern "https://.*\.devtunnels\.ms" | ForEach-Object { $_.Matches.Value }
    }
}

if ($tunnelUrl) {
    Write-Host "`n✨ Tunnel active!" -ForegroundColor Green
    Write-Host "📡 Public URL: $tunnelUrl" -ForegroundColor Cyan
    Write-Host "🔗 Forwarding to: http://localhost:$Port" -ForegroundColor Gray
    
    # Save URL to file for frontend to read
    $tunnelUrl | Out-File -FilePath "../.tunnel-url" -Encoding UTF8 -NoNewline
    
    Write-Host "`n⚠️  Keep this terminal open to maintain the tunnel." -ForegroundColor Yellow
    Write-Host "Press Ctrl+C to stop the tunnel.`n" -ForegroundColor Gray
    
    # Keep process alive
    while ($true) {
        Start-Sleep -Seconds 1
    }
} else {
    Write-Host "❌ Failed to start tunnel." -ForegroundColor Red
    exit 1
}
