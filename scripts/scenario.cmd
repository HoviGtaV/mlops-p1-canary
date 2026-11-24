@echo off
rem Launcher for scenario.ps1 that works whatever the PowerShell execution policy is.
rem Usage (from the project folder): .\scripts\scenario.cmd healthy ^| latency ^| errors ^| schema
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scenario.ps1" %*
