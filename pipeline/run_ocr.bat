@echo off
chcp 65001 >nul
title AIBLI OCR Bridge
echo ========================================
echo   AIBLI OCR Pipeline Bridge
echo ========================================
echo.
echo   用法：
echo     无参数        = 单次运行（扫描+OCR+入队）
echo     --bridge      = 纯桥接模式（已有txt -> queue）
echo     --watch       = 监控模式（持续循环）
echo     --dry-run     = 预览模式（不写入不移动）
echo.
cd /d "%~dp0"
python ocr_pipeline_bridge.py %*
if errorlevel 1 (
    echo.
    echo [ERROR] Exit code: %errorlevel%
    pause
)
