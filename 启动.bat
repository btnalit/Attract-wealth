@echo off
setlocal
title LaiCai Quick Start

cd /d "%~dp0"

REM Quick launcher: assumes venv already set up (use 一键启动.bat for first-time init)
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m uvicorn src.main:app --host 127.0.0.1 --port 8000
) else (
    echo venv not found. Please run the one-click launcher first.
    pause
)
