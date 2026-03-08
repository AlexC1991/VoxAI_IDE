@echo off
setlocal
cd /d "%~dp0"
title VoxAI RAG Healthcheck

echo ===================================================
echo      VoxAI IDE - RAG Healthcheck
echo ===================================================
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in your PATH.
    echo Please install Python 3.10+ and try again.
    pause
    exit /b 1
)

echo [INFO] Running offline RAG healthcheck...
python tests\check_rag_health.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] RAG healthcheck failed.
    pause
    exit /b 1
)

echo.
echo [OK] RAG healthcheck passed.
exit /b 0

