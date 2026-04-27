@echo off
chcp 65001 >nul
title AIBLI Pipeline GUI
echo ========================================
echo   AIBLI Pipeline Scheduler
echo ========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python not found
    pause
    exit /b 1
)

echo [INFO] Starting GUI...
cd /d "%~dp0"
python pipeline_gui.py
if errorlevel 1 (
    echo.
    echo [ERROR] Exit code: %errorlevel%
    pause
)
