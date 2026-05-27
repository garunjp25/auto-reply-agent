@echo off
REM Double-clickable launcher for the Wiki Explorer.
REM Calls the PowerShell script next to it.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-wiki.ps1"
pause
