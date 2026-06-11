@echo off
:: CodeEngine.bat — double-click to launch Code Search Engine
:: No terminal window will be visible (uses pythonw.exe).
::
:: This file can be placed anywhere — on your Desktop, pinned to Taskbar, etc.
:: Uses %~dp0 to auto-detect the directory this bat file lives in.

cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" "launcher.pyw"
