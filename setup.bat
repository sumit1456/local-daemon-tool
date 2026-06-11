@echo off
:: setup.bat — One-time setup for Code Search Engine
:: Creates venvs, installs all dependencies.
:: Run this once on a new PC, then use CodeEngine.bat to launch.

cd /d "%~dp0"

echo.
echo  ====================================
echo   Code Search Engine - Setup
echo  ====================================
echo.

:: ── Check Python ──────────────────────────────────────────────────────────
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: Python not found in PATH.
    echo  Install Python 3.11+ from https://python.org
    echo  Make sure "Add Python to PATH" is checked during install.
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo  Found Python %PYVER%

:: ── Create main venv ──────────────────────────────────────────────────────
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo  Creating main virtual environment...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo  ERROR: Failed to create .venv
        pause
        exit /b 1
    )
    echo  .venv created.
) else (
    echo  .venv already exists, skipping creation.
)

:: ── Install main dependencies ─────────────────────────────────────────────
echo.
echo  Installing main dependencies...
.venv\Scripts\pip.exe install --upgrade pip >nul 2>&1
.venv\Scripts\pip.exe install -r requirements.txt
if %errorlevel% neq 0 (
    echo  ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

:: ── Create MCP venv ───────────────────────────────────────────────────────
if not exist ".venv-mcp\Scripts\python.exe" (
    echo.
    echo  Creating MCP server virtual environment...
    python -m venv .venv-mcp
    .venv-mcp\Scripts\pip.exe install --upgrade pip >nul 2>&1
    .venv-mcp\Scripts\pip.exe install mcp httpx
    echo  .venv-mcp created.
) else (
    echo  .venv-mcp already exists, skipping creation.
)

:: ── Done ──────────────────────────────────────────────────────────────────
echo.
echo  ====================================
echo   Setup complete!
echo  ====================================
echo.
echo  Next steps:
echo    1. Double-click  CodeEngine.bat  to launch
echo    2. Or run:  .venv\Scripts\pythonw.exe launcher.pyw
echo.
pause
