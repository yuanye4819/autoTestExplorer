# AI Web Explorer - Desktop shortcut installer
$ErrorActionPreference = "Stop"

$projectDir = $PSScriptRoot
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "AI Web Explorer.lnk"

# Remove old
Remove-Item $shortcutPath -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $desktop "AI Web Tan Suo Ce Shi.lnk") -Force -ErrorAction SilentlyContinue

# Find pythonw
$pyDir = Split-Path (Get-Command python).Source -Parent
$pythonw = Join-Path $pyDir "pythonw.exe"
if (-not (Test-Path $pythonw)) {
    $pythonw = Join-Path $pyDir "python.exe"
}

$iconPath = Join-Path $projectDir "icon.ico"

$WshShell = New-Object -ComObject WScript.Shell
$s = $WshShell.CreateShortcut($shortcutPath)
$s.TargetPath = $pythonw
$s.Arguments = """$projectDir\desktop_app.py"""
$s.WorkingDirectory = $projectDir
$s.IconLocation = "$iconPath,0"
$s.WindowStyle = 7
$s.Description = "AI Web Exploration and Testing System"
$s.Save()

Write-Host "Shortcut created: $shortcutPath"
Write-Host "Icon: $iconPath"
