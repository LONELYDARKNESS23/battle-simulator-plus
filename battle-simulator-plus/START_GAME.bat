@echo off
cd /d "%~dp0"
start "" powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0Launch.ps1"
