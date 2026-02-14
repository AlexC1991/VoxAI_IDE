@echo off
title VoxAI IDE Setup & Integration

echo ===================================================
echo      VoxAI Coding Agent IDE - Setup Script
echo ===================================================
echo.

:: 1. Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.10+ and try again.
    pause
    exit /b 1
)
echo [OK] Python found.

:: 2. Check/Install Dependencies
echo.
echo [INFO] checking dependencies...
:: Ensure pip is up to date
python -m pip install --upgrade pip

:: Install requirements
:: We'll assume a requirements.txt exists, or install packages directly
if exist requirements.txt (
    pip install -r requirements.txt
) else (
    echo [INFO] requirements.txt not found, installing core packages...
    pip install PySide6 openai
)

echo.
echo [SUCCESS] Dependencies installed.
echo.

:: 3. Setup Keys
if not exist "keys\secrets.json" (
    echo [INFO] No secrets.json found. Creating from template...
    if exist "keys\secrets.template.json" (
        copy "keys\secrets.template.json" "keys\secrets.json" >nul
        echo [INFO] Created keys\secrets.json. Please edit this file to add your API keys.
    ) else (
        echo [WARN] keys\secrets.template.json missing. defaulting...
    )
) else (
    echo [OK] secrets.json exists.
)

echo.
echo ===================================================
echo Setup Complete!
echo You can now run the IDE using start_IDE.bat
echo ===================================================
echo.
pause
