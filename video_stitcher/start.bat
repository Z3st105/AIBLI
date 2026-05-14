@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ==========================================
echo   Video Stitcher - 本地视频拼接工具
echo ==========================================
echo.
echo 请选择启动模式：
echo   1. Web 服务（手动 + 流水线）
echo   2. 守护模式（自动监听并处理项目）
echo   3. 退出
echo.

set /p choice="请输入选项 (1/2/3): "

if "%choice%"=="1" goto web
if "%choice%"=="2" goto daemon
if "%choice%"=="3" goto end

echo 无效选项
pause
goto end

:web
echo.
echo 正在启动 Web 服务...
echo 浏览器将自动打开操作界面
echo.
timeout /t 2 /nobreak >nul
start http://127.0.0.1:5000
python src\web_server.py
pause
goto end

:daemon
echo.
echo 正在启动守护模式...
echo 将持续监听: ..\audio_synthesis\project_output
echo 每 30 秒扫描一次，发现新项目自动处理
echo 按 Ctrl+C 停止
echo.
python src\pipeline.py --watch-dir "%~dp0..\audio_synthesis\project_output" --daemon --interval 30
pause
goto end

:end
