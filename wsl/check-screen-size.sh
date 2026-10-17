#!/bin/bash
export DISPLAY=:99
echo "=== Xvfb 屏幕尺寸 ==="
xdpyinfo 2>/dev/null | grep -E "dimensions|screen #" | head -4
echo "=== 根窗口尺寸 ==="
xwininfo -root 2>/dev/null | grep -E "Width|Height"
echo "=== 当前窗口 ==="
for w in $(xdotool search --name ".*" 2>/dev/null); do
  n=$(xdotool getwindowname $w 2>/dev/null)
  g=$(xdotool getwindowgeometry $w 2>/dev/null | grep Geometry | tr -d ' ')
  case "$n" in Weixin|Moments|Open) echo "$w | $n | $g";; esac
done
