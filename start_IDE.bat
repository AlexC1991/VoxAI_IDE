@echo off
title VoxAI Coding Agent IDE Launcher
echo ===================================================
echo      VoxAI Coding Agent IDE - Startup
echo ===================================================

:: Check for Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in your PATH.
    echo Please install Python 3.10+ and try again.
    pause
    exit /b 1
)

:: Install Dependencies
if exist requirements.txt (
    echo [INFO] Checking/Installing dependencies...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install dependencies.
        pause
        exit /b 1
    )
) else (
    echo [WARNING] requirements.txt not found. Skipping dependency check.
)

:: Launch Application
echo [INFO] Launching IDE...
echo.
python main.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Application crashed or closed with an error.
    pause
)
