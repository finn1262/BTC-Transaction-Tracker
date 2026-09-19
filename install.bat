@echo off
setlocal
cd /d "%~dp0"

set "VENV_DIR=.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "TARGET=."

if /i "%~1"=="dev" set "TARGET=.[dev]"

if not exist "%VENV_PY%" call :create_venv
if not exist "%VENV_PY%" exit /b 1

echo Installing dependencies into "%VENV_DIR%"...
"%VENV_PY%" -m pip install --upgrade pip --disable-pip-version-check --quiet
if errorlevel 1 exit /b 1
"%VENV_PY%" -m pip install -e "%TARGET%" --disable-pip-version-check
if errorlevel 1 exit /b 1

echo.
echo Dependencies installed. Start the app with: launch.bat
exit /b 0

:create_venv
set "BOOTSTRAP_PY="
where python >nul 2>nul && set "BOOTSTRAP_PY=python"
if not defined BOOTSTRAP_PY (
    where py >nul 2>nul && set "BOOTSTRAP_PY=py -3"
)
if not defined BOOTSTRAP_PY (
    echo Python 3.14+ was not found on PATH.
    echo Install it from https://www.python.org/downloads/ and run this script again.
    exit /b 1
)
echo Creating virtual environment in "%VENV_DIR%"...
%BOOTSTRAP_PY% -m venv "%VENV_DIR%"
exit /b %errorlevel%
