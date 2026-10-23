@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%~dp0.pylibs"

if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0app.py"
) else (
  python "%~dp0app.py"
)

if errorlevel 1 (
  echo.
  echo Startup failed. Install Python 3.11+ and dependencies, see README.md.
  if not "%MT_NO_PAUSE%"=="1" pause
)
