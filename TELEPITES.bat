@echo off
rem TecF Ai telepítő – dupla kattintással indítható (rendszergazdai jogot kér)
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_windows.ps1" -NightlyLearning -OwnModel
pause
