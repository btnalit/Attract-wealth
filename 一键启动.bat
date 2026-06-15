@echo off
setlocal EnableDelayedExpansion
title LaiCai One-Click Launcher

REM ============================================================
REM  LaiCai (Attract-wealth) - Windows One-Click Launcher
REM  Detects env, installs deps, builds frontend, starts server.
REM ============================================================

cd /d "%~dp0"
set "ROOT_DIR=%CD%"
set "PYTHON_MIN_MAJOR=3"
set "PYTHON_MIN_MINOR=10"
set "FRONTEND_DIR=%ROOT_DIR%\src\frontend"
set "FRONTEND_DIST=%FRONTEND_DIR%\dist"
set "VENV_DIR=%ROOT_DIR%\.venv"

echo.
echo ============================================
echo    LaiCai One-Click Launcher
echo    %ROOT_DIR%
echo ============================================
echo.

set "OK=[OK]"
set "WARN=[!]"
set "ERR=[X]"
set "INFO=[i]"

REM ============================================================
REM Step 1/7: Detect Python
REM ============================================================
echo %INFO% [1/7] Detecting Python...

if exist "%VENV_DIR%\Scripts\python.exe" (
    set "PYTHON=%VENV_DIR%\Scripts\python.exe"
    echo   %OK% Using venv: !PYTHON!
    goto :python_ok
)

set "PYTHON="
for /f "tokens=*" %%i in ('where python 2^>nul') do (
    if not defined PYTHON set "PYTHON=%%i"
)

if not defined PYTHON goto :ask_install_python
goto :python_version_check

:ask_install_python
echo   %ERR% Python not found.
echo   Please install Python 3.10+ (3.12 recommended):
echo     https://www.python.org/downloads/
echo   Check "Add Python to PATH" during installation.
echo.
set "ANSWER="
set /p ANSWER="Install Python 3.12 via winget now? (Y/N): "
if /i not "!ANSWER!"=="Y" (
    pause
    exit /b 1
)
echo   Installing Python 3.12 ...
winget install Python.Python.3.12 --accept-source-agreements --accept-package-agreements
if !errorlevel! neq 0 (
    echo   %ERR% winget install failed. Please install manually.
    pause
    exit /b 1
)
set "PYTHON="
for /f "tokens=*" %%i in ('where python 2^>nul') do (
    if not defined PYTHON set "PYTHON=%%i"
)
if not defined PYTHON (
    echo   %ERR% Python still not found after install. Check PATH or reopen terminal.
    pause
    exit /b 1
)

:python_version_check
echo   %OK% Python: !PYTHON!
"!PYTHON!" -c "import sys; v=sys.version_info; exit(0 if (v.major>=%PYTHON_MIN_MAJOR% and v.minor>=%PYTHON_MIN_MINOR%) else 1)" 2>nul
if !errorlevel! neq 0 (
    echo   %ERR% Python version too old, need %PYTHON_MIN_MAJOR%.%PYTHON_MIN_MINOR%+
    "!PYTHON!" --version
    pause
    exit /b 1
)

:python_ok
echo   %OK% Python version check passed

REM ============================================================
REM Step 2/7: Create venv
REM ============================================================
echo.
echo %INFO% [2/7] Checking venv...

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo   Creating venv .venv - first run...
    "!PYTHON!" -m venv "%VENV_DIR%"
    if !errorlevel! neq 0 (
        echo   %ERR% Failed to create venv
        pause
        exit /b 1
    )
    echo   %OK% venv created
) else (
    echo   %OK% venv exists
)
set "PYTHON=%VENV_DIR%\Scripts\python.exe"

REM ============================================================
REM Step 3/7: Install Python dependencies
REM ============================================================
echo.
echo %INFO% [3/7] Checking Python dependencies...

"%VENV_DIR%\Scripts\python.exe" -c "import fastapi" 2>nul
if !errorlevel! neq 0 (
    echo   Installing dependencies - first run may take a few minutes...
    "%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1
    if exist "%ROOT_DIR%\requirements.txt" (
        "%VENV_DIR%\Scripts\python.exe" -m pip install -r "%ROOT_DIR%\requirements.txt"
        if !errorlevel! neq 0 (
            echo   %WARN% requirements.txt failed, trying core deps only...
            "%VENV_DIR%\Scripts\python.exe" -m pip install -e "%ROOT_DIR%"
        )
    ) else (
        "%VENV_DIR%\Scripts\python.exe" -m pip install -e "%ROOT_DIR%"
    )
    if !errorlevel! neq 0 (
        echo   %ERR% Dependency install failed. Try manually:
        echo     pip install -r requirements.txt
        pause
        exit /b 1
    )
    echo   %OK% Python dependencies installed
) else (
    echo   %OK% Python dependencies ready
)

REM ============================================================
REM Step 4/7: Detect Node.js + build frontend
REM ============================================================
echo.
echo %INFO% [4/7] Checking frontend...

if exist "%FRONTEND_DIST%\index.html" (
    echo   %OK% Frontend already built
    goto :frontend_ok
)

set "NODE_CMD="
for /f "tokens=*" %%i in ('where node 2^>nul') do (
    if not defined NODE_CMD set "NODE_CMD=%%i"
)

if not defined NODE_CMD goto :ask_install_node
goto :node_found

:ask_install_node
echo   %WARN% Frontend not built, Node.js not found.
set "ANSWER="
set /p ANSWER="Install Node.js 20 via winget now? (Y/N): "
if /i not "!ANSWER!"=="Y" (
    echo   %WARN% Skipping frontend build. Backend will run but UI may be unavailable.
    goto :frontend_ok
)
winget install OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
set "NODE_CMD="
for /f "tokens=*" %%i in ('where node 2^>nul') do (
    if not defined NODE_CMD set "NODE_CMD=%%i"
)
if not defined NODE_CMD (
    echo   %WARN% Node.js still not found. Skipping frontend build.
    goto :frontend_ok
)

:node_found
echo   %OK% Node.js: !NODE_CMD!
echo   Building frontend - first run may take a few minutes...
pushd "%FRONTEND_DIR%"
call npm install
if !errorlevel! neq 0 (
    echo   %ERR% npm install failed
    popd
    pause
    exit /b 1
)
call npm run build
if !errorlevel! neq 0 (
    echo   %ERR% Frontend build failed
    popd
    pause
    exit /b 1
)
popd
echo   %OK% Frontend build complete

:frontend_ok

REM ============================================================
REM Step 5/7: Guide .env configuration
REM ============================================================
echo.
echo %INFO% [5/7] Checking config...

if exist "%ROOT_DIR%\.env" goto :env_exists
if not exist "%ROOT_DIR%\.env.example" (
    echo   %WARN% No .env.example found, using code defaults
    goto :env_done
)
copy "%ROOT_DIR%\.env.example" "%ROOT_DIR%\.env" >nul
echo   %OK% Created .env from .env.example
echo.
echo   %WARN% Please edit .env and set at least:
echo     - LLM_API_KEY        (required for AI analysis)
echo     - LLM_BASE_URL       (default: deepseek)
echo     - TRADING_CHANNEL    (default: simulation)
echo.
set "ANSWER="
set /p ANSWER="Open .env in Notepad now? (Y/N): "
if /i "!ANSWER!"=="Y" notepad "%ROOT_DIR%\.env"
goto :env_done

:env_exists
echo   %OK% .env exists

:env_done

REM ============================================================
REM Step 6/7: Detect THS (optional)
REM ============================================================
echo.
echo %INFO% [6/7] Detecting THS (optional)...
"%VENV_DIR%\Scripts\python.exe" -c "from src.core.ths_path_resolver import resolve_ths_path; info=resolve_ths_path(); print('  THS:', 'found' if info['found'] else 'not found (simulation unaffected)')" 2>nul
if !errorlevel! neq 0 echo   Skipped THS detection

REM ============================================================
REM Step 7/7: Start service
REM ============================================================
echo.
echo %INFO% [7/7] Starting LaiCai backend...
echo.
echo ============================================
echo   URL:   http://127.0.0.1:8000
echo   Docs:  http://127.0.0.1:8000/docs
echo   Press Ctrl+C to stop
echo ============================================
echo.
echo   First startup may take 10-30s to initialize...
echo.

"%VENV_DIR%\Scripts\python.exe" -m uvicorn src.main:app --host 127.0.0.1 --port 8000

echo.
echo ============================================
echo   Service stopped
echo ============================================
pause
