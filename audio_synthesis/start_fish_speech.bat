@echo off
chcp 65001 >nul
echo ========================================
echo AIBLI Fish Speech TTS 引擎
echo ========================================
echo.

cd /d "%FISH_SPEECH_ROOT%"

echo 启动 Fish Speech WebUI...
echo 访问地址: http://127.0.0.1:7864
echo.

python tools/run_webui.py ^
    --llama-checkpoint-path checkpoints/fish-speech-1.5 ^
    --decoder-checkpoint-path checkpoints/fish-speech-1.5/firefly-gan-vq-fsq-8x1024-21hz-generator.pth ^
    --device cuda ^
    --theme light

pause
