# create_shortcut.ps1
# Run this ONCE to create a permanent Desktop shortcut for Code Search Engine.
# Usage:  Right-click → "Run with PowerShell"   OR   powershell -File create_shortcut.ps1

$ProjectDir = $PSScriptRoot
if (-not $ProjectDir) { $ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
$PythonW    = Join-Path $ProjectDir ".venv\Scripts\pythonw.exe"
$Script     = Join-Path $ProjectDir "launcher.pyw"
$Desktop    = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "Code Search Engine.lnk"

Write-Host ""
Write-Host "  Creating Desktop shortcut for Code Search Engine..." -ForegroundColor Cyan

# Verify the launcher exists
if (-not (Test-Path $Script)) {
    Write-Host "  ERROR: launcher.pyw not found at $Script" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $PythonW)) {
    Write-Host "  ERROR: pythonw.exe not found at $PythonW" -ForegroundColor Red
    Write-Host "         Make sure the .venv is set up (pip install -r requirements.txt)" -ForegroundColor Yellow
    exit 1
}

# Create the .lnk shortcut
$Shell    = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)

$Shortcut.TargetPath       = $PythonW
$Shortcut.Arguments        = "`"$Script`""
$Shortcut.WorkingDirectory = $ProjectDir
$Shortcut.Description      = "Code Search Engine - Universal Code Intelligence"
$Shortcut.WindowStyle      = 7   # 7 = minimized (hides the pythonw.exe flash)
$Shortcut.Save()

Write-Host "  Done! Shortcut created at:" -ForegroundColor Green
Write-Host "  $ShortcutPath" -ForegroundColor White
Write-Host ""
Write-Host "  You can now:" -ForegroundColor Yellow
Write-Host "    - Double-click the shortcut on your Desktop" -ForegroundColor White
Write-Host "    - Right-click it and choose 'Pin to Taskbar'" -ForegroundColor White
Write-Host "    - Right-click it and choose 'Pin to Start'" -ForegroundColor White
Write-Host ""
