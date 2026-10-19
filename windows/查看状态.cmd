@echo off
chcp 65001 >nul
rem Status overview for the WeChat bot. Double-click to run.
rem Shows bot, WeChat stack, schedule timers and health.
setlocal

set DISTRO=Ubuntu-24.04
set WSLUSER=niangao
set SCRIPT=/mnt/d/AgentPrograms/wechat-bot/wsl/botctl.sh

echo ============================================
echo   微信机器人 - 状态
echo ============================================
echo.
echo 正在读取状态...

wsl.exe -d %DISTRO% -u %WSLUSER% -e bash -lc "sh %SCRIPT% status"

if errorlevel 1 (
    echo.
    echo [失败] 没成功。把上面这堆字截图发给年糕。
) else (
    echo.
    echo [完] 以上就是当前状态。
)

echo.
pause
