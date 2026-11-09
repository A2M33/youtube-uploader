@echo off
chcp 65001 >nul
title YouTube Uploader - Install
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo [!] Python is not installed or not on PATH. Get it from https://www.python.org/downloads/
  pause
  exit /b 1
)
if not exist .venv python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
echo.
echo Done. Start the app with Start.bat
pause
