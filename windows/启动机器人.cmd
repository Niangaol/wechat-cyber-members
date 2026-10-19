@echo off
chcp 65001 >nul
rem One-click start for the WeChat bot. Double-click to run.
rem All logic lives in wsl/botctl.sh; this file only calls it.
setlocal

set DISTRO=Ubuntu-24.04
set WSLUSER=niangao
set SCRIPT=/mnt/d/AgentPrograms/wechat-bot/wsl/botctl.sh

echo ============================================
echo   微信机器人 - 启动
echo ============================================
echo.
echo 正在拉起 WSL 和服务，第一次可能要等十几秒...

wsl.exe -d %DISTRO% -u %WSLUSER% -e bash -lc "sh %SCRIPT% start"

if errorlevel 1 (
    echo.
    echo [失败] 没成功。把上面这堆字截图发给年糕。
) else (
    echo.
    echo [OK] 机器人已经在跑了。想看详细状态双击 查看状态.cmd
)

echo.
pause
