#!/bin/bash
export DISPLAY=:99
W=14680155
echo "--- 指针位置验证 ---"
xdotool mousemove 700 300
echo "after mousemove 700 300: $(xdotool getmouselocation)"
xdotool mousemove 916 613
echo "after mousemove 916 613: $(xdotool getmouselocation)"
echo "--- Open 窗口 xwininfo ---"
xwininfo -id $W 2>&1 | grep -E 'Map State|Viewable|Input|Width|Height|Absolute|Depth'
echo "--- 那个 674x26 窗口是什么 ---"
xwininfo -id 14680164 2>&1 | grep -E 'Map State|Viewable|Width|Height|Absolute'
xdotool getwindowname 14680164
echo "--- 用 --window 直送点击 Cancel（窗口内 600,400）---"
xdotool mousemove --window $W 600 400
xdotool click --window $W 1
sleep 2
xdotool search --name "^Open$" 2>/dev/null || echo "OPEN_GONE"
echo "--- 再试 XTEST 点击 Look in 下拉（绝对 716,248）---"
xdotool mousemove 716 248 click 1
sleep 1.5
import -window $W /tmp/dlg-lookin.png 2>/dev/null && echo "shot ok"
