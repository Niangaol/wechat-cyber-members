#!/bin/bash
export DISPLAY=:99
# 并行：用 --window 直送关掉 Chat History 窗口（XTEST 对 Qt 标题栏不灵）
W=14682331
timeout 10 xdotool key --window $W --clearmodifiers Escape 2>&1 | head -2
sleep 1
timeout 10 xdotool search --name "^Chat History" 2>/dev/null && echo "STILL_OPEN" || echo "CLOSED_BY_ESC"
