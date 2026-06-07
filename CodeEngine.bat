@echo off
:: CodeEngine.bat — double-click to launch Code Search Engine
:: No terminal window will be visible (uses pythonw.exe).
::
:: This file can be placed anywhere — on your Desktop, pinned to Taskbar, etc.

cd /d "C:\Users\SUMIT\Downloads\dev-tool\local-daemon-tool"
start "" ".venv\Scripts\pythonw.exe" "launcher.pyw"
