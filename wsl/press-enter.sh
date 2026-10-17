#!/bin/bash
export DISPLAY=:99
unset WAYLAND_DISPLAY
# 找当前最前面的微信窗口（Tip 对话框是独立窗口）
WID=$(xwininfo -root -tree 2>/dev/null | grep -iE '"(Weixin|wechat)"' | grep -oE '0x[0-9a-f]+' | tail -1)
echo "target window: $WID"
xdotool windowactivate --sync "$WID" 2>&1 | head -1
xdotool windowfocus --sync "$WID" 2>&1 | head -1
sleep 0.5
echo "--- 发送 Return"
xdotool key --window "$WID" --clearmodifiers Return
sleep 1
echo "--- 当前窗口树"
xwininfo -root -tree 2>/dev/null | grep -iE '"(Weixin|wechat)"' | head -4
