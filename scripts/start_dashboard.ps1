# Starts the dashboard-only server and a Cloudflare quick tunnel, and restarts either if it exits.
# Meant to run hidden at Windows logon (see scripts\install_dashboard_autostart.ps1).
# The current public URL is written to %USERPROFILE%\JobHunt\logs\dashboard-url.txt.

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo ".venv\Scripts\python.exe"
$cloudflared = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$logDir = Join-Path $env:USERPROFILE "JobHunt\logs"
$urlFile = Join-Path $logDir "dashboard-url.txt"
$port = 8080
New-Item -ItemType Directory -Force $logDir | Out-Null

function Start-Server {
    Start-Process -FilePath $python -WindowStyle Hidden -PassThru `
        -ArgumentList "scripts\serve_dashboard.py", "--port", "$port", "--git-pull-minutes", "5" `
        -WorkingDirectory $repo `
        -RedirectStandardOutput (Join-Path $logDir "server.out.log") `
        -RedirectStandardError (Join-Path $logDir "server.err.log")
}

function Start-Tunnel {
    $p = Start-Process -FilePath $cloudflared -WindowStyle Hidden -PassThru `
        -ArgumentList "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:$port" `
        -RedirectStandardOutput (Join-Path $logDir "tunnel.out.log") `
        -RedirectStandardError (Join-Path $logDir "tunnel.err.log")
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 2
        $m = Select-String -Path (Join-Path $logDir "tunnel.err.log") -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -ErrorAction SilentlyContinue | Select-Object -Last 1
        if ($m) {
            "$($m.Matches[0].Value)  (started $(Get-Date -Format 'yyyy-MM-dd HH:mm'))" | Set-Content -Path $urlFile -Encoding utf8
            break
        }
    }
    $p
}

# Adopt a server/tunnel that is already running (keeps the current public URL), start whatever is missing.
while ($true) {
    $serverUp = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $serverUp) { Start-Server | Out-Null; Start-Sleep -Seconds 2 }
    $tunnelUp = Get-Process cloudflared -ErrorAction SilentlyContinue
    if (-not $tunnelUp) { Start-Tunnel | Out-Null }
    Start-Sleep -Seconds 30
}
