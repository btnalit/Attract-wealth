@echo off
setlocal
cd /d "%~dp0\..\.."

set "PYTHON_EXE=.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
  set "PYTHON_EXE=python"
)

"%PYTHON_EXE%" scripts\smoke\run_strict_gate.py %*
exit /b %ERRORLEVEL%
