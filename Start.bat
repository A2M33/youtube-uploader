@echo off
chcp 65001 >nul
title YouTube Uploader
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo First run: installing...
  call Install.bat
)
.venv\Scripts\python -m app
pause
