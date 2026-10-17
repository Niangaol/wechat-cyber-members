#!/bin/bash
# ============================================================
# 启动 WSL 里的微信（Linux 官方版 4.1.1.8）
# 用法：wsl -d Ubuntu-24.04 -- bash /mnt/d/AgentPrograms/wechat-bot/wsl/start-wechat.sh
# ============================================================
export DISPLAY=:0
export QT_QPA_PLATFORM=xcb      # 强制走 X11：微信是 Qt 程序，WSLg 有 WAYLAND_DISPLAY，
                                 # 不强制的话它可能选 wayland 插件，xdotool/import 就看不见它

# 清理上次崩溃的残留（lock/crashinfo），避免启动即退
pkill -9 wechat 2>/dev/null; sleep 1
rm -rf ~/.xwechat/lock/* ~/.xwechat/crashinfo/* 2>/dev/null

# 后台启动，日志写 /tmp/wechat.log
nohup /usr/bin/wechat > /tmp/wechat.log 2>&1 &

sleep 3
if pgrep -f RadiumWMPF > /dev/null; then
    echo "OK 微信已启动（RadiumWMPF 引擎进程在跑）"
    echo "窗口应该已经弹到 Windows 桌面上（标题 Weixin）"
else
    echo "启动失败，看日志："
    tail -10 /tmp/wechat.log
fi
