<#
Runs one canary scenario end to end.

  .\scripts\scenario.ps1 healthy   # v2 is fine: expect PASSED (100% on v2)
  .\scripts\scenario.ps1 latency   # v2 sleeps +50 ms: expect ROLLED BACK by latency_p99
  .\scripts\scenario.ps1 errors    # v2 fails 5% of requests: expect ROLLED BACK by error_rate
  .\scripts\scenario.ps1 schema    # silent schema bug (HTTP 200): expect ROLLED BACK by score_psi

It (1) recreates variant-b with the failure flag, (2) resets the canary weight
to 0, (3) starts the rollout controller and (4) prints its progress.
#>
param(
    [ValidateSet("healthy", "latency", "errors", "schema")]
    [string]$Scenario = "healthy",
    [switch]$NoWait
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$env:B_EXTRA_LATENCY_MS = "0"; $env:B_ERROR_RATE = "0"; $env:B_SCHEMA_BUG = "0"
switch ($Scenario) {
    "latency" { $env:B_EXTRA_LATENCY_MS = "50" }
    "errors"  { $env:B_ERROR_RATE = "0.05" }
    "schema"  { $env:B_SCHEMA_BUG = "1" }
}
Write-Host "== Scenario: $Scenario  (latency=$($env:B_EXTRA_LATENCY_MS)ms error_rate=$($env:B_ERROR_RATE) schema_bug=$($env:B_SCHEMA_BUG))"

Invoke-RestMethod -Method Post -Uri http://localhost:8000/admin/weight -ContentType "application/json" -Body '{"weight": 0}' | Out-Null
# docker writes progress to stderr; PowerShell 5.1 would treat it as an error.
$ErrorActionPreference = "Continue"
docker compose up -d --no-deps variant-b 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "docker compose failed" }
$ErrorActionPreference = "Stop"

Write-Host "Waiting for variant-b to load its model ..."
for ($i = 0; $i -lt 60; $i++) {
    try { Invoke-RestMethod http://localhost:8000/health | Out-Null; break } catch { Start-Sleep 2 }
}
Start-Sleep 10   # let Prometheus collect a few scrapes of the fresh container

$r = Invoke-RestMethod -Method Post -Uri http://localhost:8090/rollout/start -ContentType "application/json" -Body '{}'
Write-Host "Rollout started. Log: $($r.log_file)"
if ($NoWait) { return }

do {
    Start-Sleep 10
    $s = Invoke-RestMethod http://localhost:8090/rollout/status
    $c = $s.last_check
    if ($c) {
        $g = ($c.guardrails.PSObject.Properties | ForEach-Object {
            "{0}={1:N4}{2}" -f $_.Name, $_.Value.value, $(if ($_.Value.breach) { "!" } else { "" }) }) -join "  "
        Write-Host ("[{0,6:P0}] v2 requests in step: {1,5}  {2}" -f $s.weight, [int]$c.n_b, $g)
    }
} while ($s.status -eq "running")

Write-Host ""
Write-Host "RESULT: $($s.status.ToUpper()) - $($s.reason)" -ForegroundColor $(if ($s.status -eq "passed") { "Green" } else { "Red" })
