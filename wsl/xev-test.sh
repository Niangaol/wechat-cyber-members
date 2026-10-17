#!/bin/bash
# xev 金标准：开一个 xev 窗口，用 XTest 点它，看 xev 报不报事件
export DISPLAY=:0

# 启动 xev（后台，事件写日志）
xev -event button -event keyboard > /tmp/xev.log 2>&1 &
XEV_PID=$!
sleep 1.5

XEV_WID=$(xdotool search --name "xev" 2>/dev/null | head -1)
echo "xev 窗口: $XEV_WID"

if [ -n "$XEV_WID" ]; then
    xdotool windowactivate "$XEV_WID" 2>/dev/null
    sleep 0.5
    # XTest 方式：移动+点击（不带 --window）
    xdotool mousemove 100 100 click 1
    sleep 0.5
    xdotool key a
    sleep 0.5
    # XSendEvent 方式：定向发给 xev 窗口
    xdotool mousemove --window "$XEV_WID" 50 50 click 1 --window "$XEV_WID" 1
    sleep 0.5
fi

kill $XEV_PID 2>/dev/null
sleep 0.5
echo "=== xev 收到的事件 ==="
grep -E "ButtonPress|ButtonRelease|KeyPress" /tmp/xev.log | head -10
COUNT=$(grep -c -E "ButtonPress|KeyPress" /tmp/xev.log)
echo "事件总数: $COUNT"
if [ "$COUNT" -gt 0 ]; then echo "XTEST_OK X 层事件通了"; else echo "XTEST_DEAD X 层完全不收"; fi
