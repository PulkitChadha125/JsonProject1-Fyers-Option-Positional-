@echo off
setlocal

REM Run from this script's directory.
cd /d "%~dp0"

set "VENV_DIR=.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "PIP_EXE=%VENV_DIR%\Scripts\pip.exe"

echo [1/5] Checking virtual environment...
if not exist "%PYTHON_EXE%" (
  echo Virtual environment not found. Creating .venv...
  python -m venv "%VENV_DIR%"
  if errorlevel 1 (
    echo Failed to create virtual environment.
    pause
    exit /b 1
  )
)

echo [2/5] Upgrading pip...
"%PYTHON_EXE%" -m pip install --upgrade pip
if errorlevel 1 (
  echo Failed to upgrade pip.
  pause
  exit /b 1
)

echo [3/5] Installing requirements...
"%PIP_EXE%" install -r requirements.txt
if errorlevel 1 (
  echo Failed to install requirements.
  pause
  exit /b 1
)

echo [4/5] Opening browser...
start "" "http://127.0.0.1:5000"

echo [5/5] Starting Flask app...
"%PYTHON_EXE%" app.py

endlocal
