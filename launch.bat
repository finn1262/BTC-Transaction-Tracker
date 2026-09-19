@echo off
setlocal
cd /d "%~dp0"

set "VENV_PY=.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo Virtual environment not found.
    echo Run install.bat first to download the dependencies.
    exit /b 1
)

"%VENV_PY%" -c "import aiohttp, textual, pydantic_settings" >nul 2>nul
if errorlevel 1 (
    echo Dependencies are missing from the virtual environment.
    echo Run install.bat first to download the dependencies.
    exit /b 1
)

"%VENV_PY%" main.py %*
exit /b %errorlevel%
