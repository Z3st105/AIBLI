@echo off
chcp 65001 >nul
echo ========================================
echo   Video Stitcher - 多角色视频拼接工具
echo ========================================
echo.

if "%~1"=="" (
    echo 用法: run.bat [项目ID] [输出文件名(可选)]
    echo 示例: run.bat 111
    echo 示例: run.bat 111 myvideo.mp4
    echo.
    pause
    exit /b 1
)

set PROJECT_ID=%~1
set OUTPUT_FILE=%~2

if not "%~2"=="" (
    python src/main.py --project %PROJECT_ID% --output output/%OUTPUT_FILE%
) else (
    python src/main.py --project %PROJECT_ID%
)

if %errorlevel% neq 0 (
    echo.
    echo [错误] 执行失败，请检查上面的日志。
    pause
    exit /b %errorlevel%
)

echo.
echo ✅ 完成！
pause
