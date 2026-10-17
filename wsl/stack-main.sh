#!/bin/bash
# 常驻保活：Xvfb :99 + x11vnc + noVNC + 微信
# 教训（2026-10-16 实录）：
#  1) 必须 setsid 拉起（systemd 下 nohup & 会被吞）
#  2) 存活判断按 X 窗口，不按进程名（pgrep -f RadiumWMPF 会被外层 cmdline 误报）
#  3) 微信起不来 = Xvfb 攒了僵尸 selection，必须重启 Xvfb（不能因为它活着就跳过）
unset WAYLAND_DISPLAY
export DISPLAY=:99
export QT_QPA_PLATFORM=xcb

spawn() {
    setsid nohup "$@" > /dev/null 2>&1 < /dev/null &
    disown 2>/dev/null || true
}

wechat_alive() {
    DISPLAY=:99 xwininfo -root -tree 2>/dev/null | grep -q '"Weixin"'
}

restart_xvfb() {
    pkill -9 -f "Xvfb :99" 2>/dev/null
    sleep 2
    rm -f /tmp/.X99-lock
    spawn Xvfb :99 -screen 0 1280x800x24
    sleep 3
    # X 服务器换了，x11vnc/websockify 也要重拉
    pkill -9 -f "x11vnc -display :99" 2>/dev/null; sleep 1
    spawn x11vnc -display :99 -localhost -nopw -forever -shared
    sleep 2
    pkill -9 -f "websockify.*6080" 2>/dev/null; sleep 1
    spawn websockify --web=/usr/share/novnc 127.0.0.1:6080 localhost:5900
    sleep 2
}

start_wechat() {
    pkill -9 -x wechat 2>/dev/null
    pkill -9 -f RadiumWMPF 2>/dev/null
    sleep 2
    rm -rf ~/.xwechat/lock/* ~/.xwechat/crashinfo/* 2>/dev/null
    spawn /usr/bin/wechat
    sleep 8
}

ensure_vnc() {
    # 四个组件各自独立保活，互不为前提：
    #   Xvfb 活着不代表 x11vnc/websockify 活着（2026-10-16 实测：noVNC 打不开）
    #   Xvfb 活着也不代表有窗口管理器——没有 WM 时 xdotool windowactivate
    #   直接报 _NET_ACTIVE_WINDOW 不支持，鼠标点击时好时坏（实测点击无反应）
    pgrep -f "Xvfb :99" > /dev/null || { rm -f /tmp/.X99-lock; spawn Xvfb :99 -screen 0 1280x800x24; sleep 3; }
    pgrep -f "x11vnc -display :99" > /dev/null || { spawn x11vnc -display :99 -localhost -nopw -forever -shared; sleep 2; }
    pgrep -f "websockify.*6080" > /dev/null || { spawn websockify --web=/usr/share/novnc 127.0.0.1:6080 localhost:5900; sleep 2; }
    pgrep -x openbox > /dev/null || { spawn openbox --sm-disable; sleep 2; }
}

ensure_vnc

# 微信不在 → 先杀再起；起不来 → 重启 Xvfb 清僵尸 selection 再起
if ! wechat_alive; then
    start_wechat
fi
if ! wechat_alive; then
    echo "微信首次启动失败，重启 Xvfb 清僵尸 selection 后重试"
    restart_xvfb
    start_wechat
fi
wechat_alive && echo "STACK_UP" || echo "STACK_DEGRADED"

# 保活：10 分钟一轮；微信不在同样走「先杀再起→不行重启 Xvfb」两级恢复
while true; do
    sleep 600
    ensure_vnc
    if ! wechat_alive; then
        start_wechat
        if ! wechat_alive; then
            restart_xvfb
            start_wechat
        fi
    fi
done
