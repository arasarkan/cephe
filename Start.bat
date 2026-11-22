@echo off
rem Starts Cephe and opens it in the browser. Closing this window quits the app.
chcp 65001 >nul
cd /d "%~dp0"
if not exist config.json (
  echo Run Install.bat first.
  pause
  exit /b 1
)
set "PY="
for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "(Get-Content -Raw -Encoding UTF8 config.json | ConvertFrom-Json).python"`) do set "PY=%%p"
if not defined PY (
  echo config.json is damaged. Run Install.bat again.
  pause
  exit /b 1
)
title Cephe
"%PY%" "%~dp0app\server.py"
if errorlevel 1 pause
