# TecF Ai – útmutató Claude számára

Saját, offline is működő, önállóan tanuló AI asszisztens Windowsra. A felhasználó magyar:
**mindig magyarul válaszolj**, egyszerűen, szakzsargon nélkül. A program felülete, üzenetei és
kommentjei is magyarok; a kódban az azonosítók angolok.

## A felhasználó gépe
- Windows 11 Pro, i7-13645HX (14 mag), 16 GB RAM
- NVIDIA GeForce RTX 4050 Laptop GPU, 6 GB VRAM (a meghajtó ~5,99 GB-ot jelent)
- Telepítés helye: `D:\TecFAi` (app: `D:\TecFAi\app`, Python környezet: `D:\TecFAi\venv`)
- Ollama modell: `qwen3:8b`; saját modell alapja: `Qwen/Qwen3-1.7B` (LoRA)

## Felépítés
- `tecf/` – a program (`python -m tecf` = ablak, `python -m tecf <parancs>` = parancssor)
  - `brain.py` agy (modellválasztás, tudás-előhívás, eszközhasználat), `knowledge.py` tudásbázis (SQLite FTS5)
  - `learning.py` tanuló üzem, `bootstrap.py` alaptudás letöltése, `providers/` 27 AI szolgáltató
  - `tools/` eszközök (rendszer, fájl, dokumentum, web, hálózat), `gui.py` ablak (tkinter)
  - `llm/` saját nyelvi modell: `base.py` Qwen3 + LoRA hangolás, `train.py` nulláról tanítás
  - `updater.py` önfrissítés GitHubról (csak az `app` mappát cseréli)
- `scripts/install_windows.ps1` telepítő, `TELEPITES.bat` dupla kattintásos indítója
- `tests/` – `python -m unittest discover -s tests`

## Szabályok
- Fejlesztés a `claude/zen-curie-2u6xui` ágon; a felhasználó gépe a ⟳ Frissítés gombbal
  erről az ágról frissít, tehát ami ide kerül, az hozzá is eljut. Push előtt fussanak a tesztek.
- A felhasználó adatait (`D:\TecFAi\data`, `config`, `models`, `hf_cache`, `sajat_modell`) soha ne töröld.
- Az alapcsomag csak a Python standard könyvtárát használja; a többi opcionális
  (`requirements-optional.txt`, `requirements-train.txt`).
- Windows: a PowerShell 5.1 BOM-mal írja az UTF-8 fájlokat – JSON olvasásnál `utf-8-sig`.
  A `python` parancs lehet a Microsoft Store álparancsa (WindowsApps) – ne bízz benne.
- Veszélyes műveletek (parancsfuttatás, fájlírás, hálózati eszköz konfiguráció) előtt mindig jóváhagyás kell.

## Ha a gépen dolgozol
A telepített példány kipróbálása: `D:\TecFAi\tecf.bat <parancs>` vagy `D:\TecFAi\tecf.bat gui`.
Hibanapló: `D:\TecFAi\logs\hiba.log`. Fejlesztés után: tesztek, commit, push, majd a telepített
példányban `D:\TecFAi\tecf.bat update`.
