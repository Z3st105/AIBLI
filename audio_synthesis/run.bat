@echo off
chcp 65001 >nul
cd /d "%~dp0"

if "%~1"=="" (
    echo 用法: run.bat [项目名] [文案文件名]
    echo 示例: run.bat P999 P999_初次合作
    echo.
    echo 可用文案:
    dir /b scripts\*.txt 2>nul
    pause
    exit /b 1
)

set PROJECT=%~1
set SCRIPT=%~2

echo [启动] 项目: %PROJECT%, 文案: scripts\%SCRIPT%.txt
engine\runtime\python.exe audio_synthesis_pipeline.py --project %PROJECT% --script "scripts\%SCRIPT%.txt"

if %errorlevel% neq 0 (
    echo [ERROR] 运行失败，错误码: %errorlevel%
    pause
) else (
    echo [完成] 输出已保存到 project_output\%PROJECT%\
    pause
)
