#!/bin/bash
export DISPLAY=:99
echo "--- openbox 进程"
pgrep -a openbox || echo "(not running)"
echo "--- root window WM 属性"
xprop -root _NET_SUPPORTING_WM_CHECK _NET_WM_NAME _NET_ACTIVE_WINDOW 2>&1 | head -6
echo "--- WM 检测"
command -v xprop >/dev/null && xprop -root | grep -c "_NET" || echo "xprop missing"
echo "--- 窗口树"
xwininfo -root -tree 2>/dev/null | grep -iE "weixin|wechat" | head -5
