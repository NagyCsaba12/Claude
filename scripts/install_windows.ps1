# TecF Ai telepítő – Windows, D: meghajtó
# Futtatás (rendszergazdai PowerShell):
#   Set-ExecutionPolicy -Scope Process Bypass; .\scripts\install_windows.ps1
param(
    [string]$Target = "D:\TecFAi",
    [switch]$NoOllama,
    [switch]$NoBootstrap,
    [switch]$NightlyLearning,
    [switch]$OwnModel
)
$ErrorActionPreference = "Stop"
$Src = Split-Path -Parent $PSScriptRoot

Write-Host "== TecF Ai telepítés: $Target ==" -ForegroundColor Cyan
if (-not (Test-Path "D:\")) { throw "Nincs D: meghajtó. Adj meg másik célt: -Target E:\TecFAi" }

# Külső parancs futtatása; hiba esetén megáll, és érthető üzenetet ír
function Invoke-Step([string]$What, [scriptblock]$Cmd) {
    & $Cmd
    if ($LASTEXITCODE -ne 0) { throw "Hiba ennél a lépésnél: $What (kilépési kód: $LASTEXITCODE)" }
}

# Valódi Python keresése. A Windows 11 'python' parancsa gyakran csak a Microsoft Store
# parancsikonja (WindowsApps), ami nem működő Python – ezt kihagyjuk.
function Get-RealPython {
    $ErrorActionPreference = "Continue"  # egy hibás jelölt ne állítsa le a telepítőt
    $cands = @()
    $cands += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python31[0-3]\python.exe",
                            "$env:ProgramFiles\Python31[0-3]\python.exe" -ErrorAction SilentlyContinue |
              Sort-Object { $_.FullName -notmatch "Python312" }, FullName | ForEach-Object FullName
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notmatch "WindowsApps") { $cands += $cmd.Source }
    foreach ($p in $cands) {
        $v = & $p -c "import sys, tkinter, venv; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v -and [version]$v -ge [version]"3.10" -and [version]$v -lt [version]"3.14") {
            return $p
        }
    }
    return $null
}

# 1) Python
$py = Get-RealPython
if (-not $py) {
    Write-Host "Python 3.12 telepítése (winget)..."
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    $py = Get-RealPython
}
if (-not $py) {
    throw "Nem sikerült Pythont telepíteni. Telepítsd kézzel: https://www.python.org/downloads/ (3.12), majd futtasd újra."
}
Write-Host "Python: $py"

# 2) Programfájlok másolása
New-Item -ItemType Directory -Force -Path "$Target\app" | Out-Null
Copy-Item -Recurse -Force "$Src\tecf", "$Src\requirements-optional.txt", "$Src\requirements-train.txt", "$Src\README.md" "$Target\app\"
Copy-Item -Force "$Src\scripts\tecf.bat" "$Target\tecf.bat"

# 3) Saját Python környezet + opcionális csomagok (PDF, Word, Excel, SSH/hálózat)
if (-not (Test-Path "$Target\venv\Scripts\pythonw.exe")) {
    # egy korábbi, félbemaradt telepítés maradványa
    Remove-Item -Recurse -Force "$Target\venv" -ErrorAction SilentlyContinue
    Invoke-Step "Python környezet létrehozása" { & $py -m venv "$Target\venv" }
}
$vpy = "$Target\venv\Scripts\python.exe"
Invoke-Step "pip frissítése" { & $vpy -m pip install --upgrade pip }
Invoke-Step "kiegészítő csomagok" { & $vpy -m pip install -r "$Target\app\requirements-optional.txt" }

# 3b) Saját nyelvi modell tanításához: PyTorch (NVIDIA kártyánál GPU-s változat)
if ($OwnModel) {
    $nvidia = Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match "NVIDIA" }
    if ($nvidia) {
        Write-Host "NVIDIA kártya: $($nvidia[0].Name) -> PyTorch GPU változat"
        Invoke-Step "PyTorch (GPU)" { & $vpy -m pip install torch --index-url https://download.pytorch.org/whl/cu128 }
    } else {
        Write-Host "Nincs NVIDIA kártya -> PyTorch CPU változat (a tanítás lassabb lesz)"
        Invoke-Step "PyTorch (CPU)" { & $vpy -m pip install torch --index-url https://download.pytorch.org/whl/cpu }
    }
    Invoke-Step "modelltanító csomagok" { & $vpy -m pip install -r "$Target\app\requirements-train.txt" }
    # a letöltött alapmodellek (Hugging Face) is a D: meghajtóra kerüljenek
    [Environment]::SetEnvironmentVariable("HF_HOME", "$Target\hf_cache", "User")
}

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
Invoke-Step "TecF Ai inicializálása" { & "$Target\tecf.bat" init }
$cfgPath = "$Target\config\config.json"
$cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
$cfg.local_model = $model
# BOM nélküli UTF-8 (a Windows PowerShell 5.1 "UTF8" kódolása BOM-ot írna a fájl elejére)
[IO.File]::WriteAllText($cfgPath, ($cfg | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding $false))

# 6) Alaptudás letöltése a netről (legjobb hiteles források)
if (-not $NoBootstrap) { & "$Target\tecf.bat" bootstrap }

# 7) Opcionális: éjszakai tanuló üzem (minden nap 02:00, 90 percig)
if ($NightlyLearning) {
    $action = New-ScheduledTaskAction -Execute "$Target\tecf.bat" -Argument "learn --loop --minutes 90"
    $trigger = New-ScheduledTaskTrigger -Daily -At 2am
    Register-ScheduledTask -TaskName "TecF Ai tanulás" -Action $action -Trigger $trigger -Force | Out-Null
    Write-Host "Éjszakai tanulás ütemezve (02:00)."
}

# 7b) Ellenőrzés: elindul-e az ablakos program (tkinter + a program betöltése)
Invoke-Step "ablakos program ellenőrzése" {
    & $vpy -c "import sys; sys.path.insert(0, r'$Target\app'); import tkinter, tecf.gui; print('Ablakos program: OK')"
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
