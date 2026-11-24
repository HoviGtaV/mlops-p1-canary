<#
Runs one canary scenario end to end.

On Windows, start it through the launcher next to it, which works whatever the
PowerShell execution policy is:

  .\scripts\scenario.cmd healthy   # v2 is fine: expect PASSED (100% on v2)
  .\scripts\scenario.cmd latency   # v2 sleeps +50 ms: expect ROLLED BACK by latency_p99
  .\scripts\scenario.cmd errors    # v2 fails 5% of requests: expect ROLLED BACK by error_rate
  .\scripts\scenario.cmd schema    # silent schema bug (HTTP 200): expect ROLLED BACK by score_psi

It (1) stops a rollout that is still running, (2) resets the canary weight to 0,
(3) recreates variant-b with the failure flag, (4) starts the rollout controller
and (5) prints its progress.
#>
param(
    [ValidateSet("healthy", "latency", "errors", "schema")]
    [string]$Scenario = "healthy",
    [switch]$NoWait
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$controller = "http://localhost:8090"
$router = "http://localhost:8000"

# 1. A rollout still running (e.g. the previous scenario) would refuse a new start: stop it.
try { $st = Invoke-RestMethod "$controller/rollout/status" }
catch { throw "The controller is not reachable on $controller. Is the stack running? (docker compose up -d)" }
if ($st.status -eq "running") {
    Write-Host "A rollout is still running: aborting it first ..."
    Invoke-RestMethod -Method Post "$controller/rollout/abort" | Out-Null
    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep 2
        if ((Invoke-RestMethod "$controller/rollout/status").status -ne "running") { break }
    }
}

$flags = @{ B_EXTRA_LATENCY_MS = "0"; B_ERROR_RATE = "0"; B_SCHEMA_BUG = "0" }
switch ($Scenario) {
    "latency" { $flags.B_EXTRA_LATENCY_MS = "50" }
    "errors"  { $flags.B_ERROR_RATE = "0.05" }
    "schema"  { $flags.B_SCHEMA_BUG = "1" }
}
Write-Host "== Scenario: $Scenario  (latency=$($flags.B_EXTRA_LATENCY_MS)ms error_rate=$($flags.B_ERROR_RATE) schema_bug=$($flags.B_SCHEMA_BUG))"

# 2. Nobody on v2 while it restarts.
Invoke-RestMethod -Method Post -Uri "$router/admin/weight" -ContentType "application/json" -Body '{"weight": 0}' | Out-Null

# 3. Recreate variant-b with the flags. They are set only for this one command and removed
#    right after, so a later "docker compose up -d" in the same window cannot pick them up.
foreach ($k in $flags.Keys) { Set-Item "Env:$k" $flags[$k] }
$ErrorActionPreference = "Continue"   # docker writes progress to stderr; PowerShell 5.1 would treat it as an error
docker compose up -d --no-deps variant-b 2>&1 | Out-Null
$code = $LASTEXITCODE
$ErrorActionPreference = "Stop"
foreach ($k in $flags.Keys) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
if ($code -ne 0) { throw "docker compose failed to recreate variant-b" }

Write-Host "Waiting for variant-b to load its model ..."
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    try { Invoke-RestMethod "$router/health" | Out-Null; $ready = $true; break } catch { Start-Sleep 2 }
}
if (-not $ready) { throw "variant-b did not become healthy within 2 minutes (docker compose logs variant-b)" }
Start-Sleep 10   # let Prometheus collect a few scrapes of the fresh container

# 4. Start the rollout with the shipped settings.
$r = Invoke-RestMethod -Method Post -Uri "$controller/rollout/start" -ContentType "application/json" -Body '{}'
Write-Host "Rollout started. Log: $($r.log_file)"
if ($NoWait) { return }

# 5. Progress every 10 s ("!" marks a guardrail breached at that check).
$s = [pscustomobject]@{ status = "running" }
do {
    Start-Sleep 10
    # A temporary error reading the status must not stop the script (the rollout goes on).
    try { $s = Invoke-RestMethod "$controller/rollout/status" }
    catch { Write-Host "(status temporarily unavailable, retrying)"; continue }
    $c = $s.last_check
    if ($c) {
        $g = ($c.guardrails.PSObject.Properties | ForEach-Object {
            "{0}={1:N4}{2}" -f $_.Name, $_.Value.value, $(if ($_.Value.breach) { "!" } else { "" }) }) -join "  "
        Write-Host ("[{0,6:P0}] v2 requests in step: {1,5}  {2}" -f $s.weight, [int]$c.n_b, $g)
    }
} while ($s.status -eq "running")

Write-Host ""
Write-Host "RESULT: $($s.status.ToUpper()) - $($s.reason)" -ForegroundColor $(if ($s.status -eq "passed") { "Green" } else { "Red" })
