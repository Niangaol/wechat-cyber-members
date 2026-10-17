#!/bin/bash
export DISPLAY=:99
echo "--- 当前窗口 ---"
xdotool search --name ".*" 2>/dev/null | while read -r w; do
  n=$(xdotool getwindowname "$w" 2>/dev/null)
  g=$(xdotool getwindowgeometry "$w" 2>/dev/null | tr '\n' ' ')
  [ -n "$n" ] && echo "$w | $n | $g"
done
echo "--- 尝试抓 WeChat 窗口 ---"
for W in $(xdotool search --name "^WeChat$" 2>/dev/null); do
  echo "trying $W"
  import -window $W /tmp/wechat-win.png 2>&1 && echo "OK $(stat -c%s /tmp/wechat-win.png) bytes" || echo "FAIL"
done
echo "--- xwininfo 映射状态 ---"
for W in $(xdotool search --name "^WeChat$" 2>/dev/null); do
  xwininfo -id $W 2>&1 | grep -E 'Map State|Width|Height|Absolute'
done
