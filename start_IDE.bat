@echo off
setlocal enabledelayedexpansion
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

:: Check/Build Go vector engine dependency
set "ENGINE_DIR=Vox_RIG\search_engine"
set "ENGINE_BIN=%ENGINE_DIR%\vox-vector-engine.exe"
set "ENGINE_OK=0"
echo.
if exist "%ENGINE_BIN%" call :check_engine
if "!ENGINE_OK!"=="0" call :build_engine
if "!ENGINE_OK!"=="0" if exist "%ENGINE_BIN%" call :check_engine

if "!ENGINE_OK!"=="1" echo [OK] Vector engine dependency check passed.
if "!ENGINE_OK!"=="0" if exist "%ENGINE_BIN%" echo [WARNING] Vector engine exists but appears invalid - zero bytes.
if "!ENGINE_OK!"=="0" if not exist "%ENGINE_BIN%" echo [WARNING] Vector engine binary not available. Running with fallback behavior.

:: Launch Application
echo [INFO] Launching IDE...
echo.
python main.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Application crashed or closed with an error.
    pause
)

goto :eof

:check_engine
set "ENGINE_OK=0"
for %%I in ("%ENGINE_BIN%") do set "ENGINE_SIZE=%%~zI"
if "!ENGINE_SIZE!"=="0" (
    echo [WARNING] Go vector engine file is empty. Rebuilding...
    del /f /q "%ENGINE_BIN%" >nul 2>&1
    exit /b 0
)
echo [OK] Go vector engine found: %ENGINE_BIN%
set "ENGINE_OK=1"
exit /b 0

:build_engine
echo [INFO] Go vector engine not found. Attempting build...
where go >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] Go is not installed or not in PATH.
    echo [WARNING] RAG engine binary was not built. IDE will run with fallback behavior.
    exit /b 0
)
pushd "%ENGINE_DIR%"
go build -o vox-vector-engine.exe .
if %errorlevel% neq 0 (
    echo [WARNING] Failed to build Go vector engine.
    echo [WARNING] IDE will run, but RAG may be slower until this is fixed.
    popd
    exit /b 0
)
popd
echo [OK] Built Go vector engine: %ENGINE_BIN%
set "ENGINE_OK=1"
exit /b 0
