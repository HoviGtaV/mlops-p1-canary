<#
Saves a PNG of the Grafana dashboard with headless Microsoft Edge (no install needed).

  .\scripts\screenshot.ps1 -Name healthy -Minutes 15
#>
param([string]$Name = "dashboard", [int]$Minutes = 15, [long]$FromMs = 0, [long]$ToMs = 0)
$root = Split-Path $PSScriptRoot -Parent
$out = Join-Path $root "report\figures\grafana_$Name.png"
$edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
          "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $edge) { throw "Microsoft Edge not found" }
$range = if ($FromMs -gt 0) { "from=$FromMs&to=$ToMs" } else { "from=now-${Minutes}m&to=now" }
$url = "http://localhost:3000/d/p1-canary/?orgId=1&kiosk&$range&refresh="
$profile = Join-Path $env:TEMP "p1-edge-shot"
& $edge --headless=new --disable-gpu --hide-scrollbars --user-data-dir="$profile" `
    --window-size=1800,1420 --virtual-time-budget=15000 --screenshot="$out" $url 2>$null | Out-Null
Start-Sleep 2
if (Test-Path $out) { Write-Host "saved $out" } else { Write-Host "screenshot failed" }
