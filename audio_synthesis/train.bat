@echo off
chcp 65001 >nul
cd /d "%~dp0\engine"

set PYTHON=runtime\python.exe
set SCRIPT=auto_train_gui.py

if not exist %PYTHON% (
    echo [ERROR] 找不到 Python 运行时: %PYTHON%
    pause
    exit /b 1
)

if not exist %SCRIPT% (
    echo [ERROR] 找不到训练脚本: %SCRIPT%
    pause
    exit /b 1
)

echo [启动] GPT-SoVITS 训练 GUI...
echo [提示] 训练完成后，记得把新角色的模型复制到 character_profile\角色名\ 下
echo.

%PYTHON% %SCRIPT%

if %errorlevel% neq 0 (
    echo [ERROR] GUI 退出异常，错误码: %errorlevel%
    pause
)
