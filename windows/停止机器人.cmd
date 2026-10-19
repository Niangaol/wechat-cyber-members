@echo off
chcp 65001 >nul
rem One-click stop for the WeChat bot. Double-click to run.
rem Only the bot stops; WeChat itself (wechat-stack) stays up so restart is instant.
setlocal

set DISTRO=Ubuntu-24.04
set WSLUSER=niangao
set SCRIPT=/mnt/d/AgentPrograms/wechat-bot/wsl/botctl.sh

echo ============================================
echo   微信机器人 - 停止
echo ============================================
echo.
echo 正在停止机器人...

wsl.exe -d %DISTRO% -u %WSLUSER% -e bash -lc "sh %SCRIPT% stop"

if errorlevel 1 (
    echo.
    echo [失败] 没成功。把上面这堆字截图发给年糕。
) else (
    echo.
    echo [OK] 机器人已停。排班定时器已禁用，不会自己再活过来。
)

echo.
pause
