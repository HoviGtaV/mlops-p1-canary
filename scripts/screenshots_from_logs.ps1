<#
Re-takes one Grafana screenshot per rollout in data/rollouts, zoomed on that rollout.
#>
$root = Split-Path $PSScriptRoot -Parent
$summary = Get-Content (Join-Path $root "data\report_figures\rollouts_summary.json") -Raw | ConvertFrom-Json
foreach ($r in $summary) {
    $t0 = [long]($r.file -replace "rollout-(\d+)\.jsonl", '$1')
    $from = ($t0 - 30) * 1000
    $to = [long](($t0 + $r.seconds + 45) * 1000)
    & (Join-Path $PSScriptRoot "screenshot.ps1") -Name $r.scenario -FromMs $from -ToMs $to
}
