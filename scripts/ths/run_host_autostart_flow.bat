@echo off
setlocal

set "ROOT=%~dp0..\.."
if exist "%ROOT%\.venv\Scripts\python.exe" (
  set "PY=%ROOT%\.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

"%PY%" "%ROOT%\scripts\ths\run_host_autostart_flow.py" --start-xiadan-if-missing %*
exit /b %errorlevel%
