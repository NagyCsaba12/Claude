@echo off
rem TecF Ai indító – a telepítési könyvtárból (pl. D:\TecFAi) fut
set "TECF_HOME=%~dp0"
set "TECF_HOME=%TECF_HOME:~0,-1%"
set "PYTHONPATH=%TECF_HOME%\app"
set "OLLAMA_MODELS=%TECF_HOME%\models"
chcp 65001 >nul
"%TECF_HOME%\venv\Scripts\python.exe" -m tecf %*
