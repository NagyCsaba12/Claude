# TecF Ai telepítő – Windows, D: meghajtó
# Futtatás (rendszergazdai PowerShell):
#   Set-ExecutionPolicy -Scope Process Bypass; .\scripts\install_windows.ps1
param(
    [string]$Target = "D:\TecFAi",
    [switch]$NoOllama,
    [switch]$NoBootstrap,
    [switch]$NightlyLearning
)
$ErrorActionPreference = "Stop"
$Src = Split-Path -Parent $PSScriptRoot

Write-Host "== TecF Ai telepítés: $Target ==" -ForegroundColor Cyan
if (-not (Test-Path "D:\")) { throw "Nincs D: meghajtó. Adj meg másik célt: -Target E:\TecFAi" }

# 1) Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Python telepítése (winget)..."
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

# 2) Programfájlok másolása
New-Item -ItemType Directory -Force -Path "$Target\app" | Out-Null
Copy-Item -Recurse -Force "$Src\tecf", "$Src\requirements-optional.txt", "$Src\README.md" "$Target\app\"
Copy-Item -Force "$Src\scripts\tecf.bat" "$Target\tecf.bat"

# 3) Saját Python környezet + opcionális csomagok (PDF, Word, Excel, SSH/hálózat)
python -m venv "$Target\venv"
& "$Target\venv\Scripts\python.exe" -m pip install --upgrade pip
& "$Target\venv\Scripts\python.exe" -m pip install -r "$Target\app\requirements-optional.txt"

# 4) Offline nyelvi modell (Ollama) – a gép memóriájához illő legjobb nyílt modell
$ramGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
if     ($ramGB -ge 48) { $model = "qwen3:32b" }
elseif ($ramGB -ge 24) { $model = "qwen3:14b" }
elseif ($ramGB -ge 12) { $model = "qwen3:8b" }
else                   { $model = "qwen3:4b" }
Write-Host "RAM: $ramGB GB -> helyi modell: $model  (később cserélhető: config.json local_model)"

if (-not $NoOllama) {
    if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
        winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
        $env:Path += ";$env:LOCALAPPDATA\Programs\Ollama"
    }
    # A modellek is a D: meghajtóra kerüljenek
    [Environment]::SetEnvironmentVariable("OLLAMA_MODELS", "$Target\models", "User")
    $env:OLLAMA_MODELS = "$Target\models"
    ollama pull $model
}

# 5) Inicializálás + beállítások
[Environment]::SetEnvironmentVariable("TECF_HOME", $Target, "User")
$env:TECF_HOME = $Target
& "$Target\tecf.bat" init
$cfgPath = "$Target\config\config.json"
$cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
$cfg.local_model = $model
$cfg | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 $cfgPath

# 6) Alaptudás letöltése a netről (legjobb hiteles források)
if (-not $NoBootstrap) { & "$Target\tecf.bat" bootstrap }

# 7) Opcionális: éjszakai tanuló üzem (minden nap 02:00, 90 percig)
if ($NightlyLearning) {
    $action = New-ScheduledTaskAction -Execute "$Target\tecf.bat" -Argument "learn --loop --minutes 90"
    $trigger = New-ScheduledTaskTrigger -Daily -At 2am
    Register-ScheduledTask -TaskName "TecF Ai tanulás" -Action $action -Trigger $trigger -Force | Out-Null
    Write-Host "Éjszakai tanulás ütemezve (02:00)."
}

# 8) Asztali és Start menü parancsikon (ablakos program, konzol nélkül)
$ws = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    $lnk = $ws.CreateShortcut("$dir\TecF Ai.lnk")
    $lnk.TargetPath = "$Target\venv\Scripts\pythonw.exe"
    $lnk.Arguments = "-m tecf gui"
    $lnk.WorkingDirectory = "$Target\app"
    $lnk.Description = "TecF Ai - saját tanuló mesterséges intelligencia"
    $lnk.Save()
}

Write-Host "`nKész! Indítás: asztali 'TecF Ai' ikon, vagy parancssorból: $Target\tecf.bat chat" -ForegroundColor Green
