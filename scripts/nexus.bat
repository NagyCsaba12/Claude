@echo off
rem NEXUS AI indító – a telepítési könyvtárból (pl. D:\NexusAI) fut
set "NEXUS_HOME=%~dp0"
set "NEXUS_HOME=%NEXUS_HOME:~0,-1%"
set "PYTHONPATH=%NEXUS_HOME%\app"
set "OLLAMA_MODELS=%NEXUS_HOME%\models"
chcp 65001 >nul
"%NEXUS_HOME%\venv\Scripts\python.exe" -m nexus %*
