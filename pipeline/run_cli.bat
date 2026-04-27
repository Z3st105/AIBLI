@echo off
chcp 65001 >nul
title AIBLI Pipeline CLI
echo ========================================
echo   AIBLI Pipeline Scheduler - CLI
echo ========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python not found
    pause
    exit /b 1
)

cd /d "%~dp0"
python pipeline_orchestrator.py
