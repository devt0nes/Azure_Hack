# Day 4: Stop Azure Dev Tunnel

param(
    [Parameter(Mandatory=$false)]
    [string]$TunnelName = "platform-preview"
)

Write-Host "🛑 Stopping tunnel '$TunnelName'..." -ForegroundColor Yellow

# Get tunnel ID
$tunnelId = (devtunnel list --output json 2>&1 | ConvertFrom-Json | Where-Object { $_.tunnelName -eq $TunnelName }).tunnelId

if ($tunnelId) {
    # Delete tunnel
    devtunnel delete $tunnelId -f
    Write-Host "✅ Tunnel stopped and removed." -ForegroundColor Green
    
    # Clean up tunnel URL file
    if (Test-Path "../.tunnel-url") {
        Remove-Item "../.tunnel-url"
    }
} else {
    Write-Host "⚠️  Tunnel '$TunnelName' not found." -ForegroundColor Yellow
}
