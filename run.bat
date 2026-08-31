@echo off
setlocal enabledelayedexpansion

echo ===================================================
echo        Starting Email Assistant Local Server
echo ===================================================

cd /d "%~dp0"

:: Check if Python is installed
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not found in PATH. Please install Python 3.11+.
    pause
    exit /b 1
)

:: Create virtual environment if not present
if not exist "venv" (
    echo [INFO] Creating virtual environment 'venv'...
    python -m venv venv
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

:: Activate virtual environment
echo [INFO] Activating virtual environment...
call venv\Scripts\activate.bat

:: Install / Update dependencies
echo [INFO] Installing required dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

:: Copy .env.example to .env if .env doesn't exist
if not exist ".env" (
    echo [INFO] Creating default .env configuration file...
    copy .env.example .env >nul
)

:: Launch FastAPI Uvicorn server
echo [INFO] Launching Email Assistant server at http://127.0.0.1:8080 ...
echo [INFO] Press Ctrl+C to terminate the server.
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8080 --reload

pause
