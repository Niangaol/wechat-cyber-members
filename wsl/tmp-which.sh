#!/bin/bash
export DISPLAY=:99
# 鼠标移到目标点，看落在哪个窗口
xdotool mousemove 700 646
sleep 0.3
eval $(xdotool getmouselocation --shell)
echo "mouse at $X,$Y"
# 找该点最前面的窗口
for w in $(xdotool search --name ".*" 2>/dev/null); do
  geo=$(xwininfo -id $w 2>/dev/null | grep -E "Absolute upper-left|Width|Height" | tr '\n' ' ')
  name=$(xdotool getwindowname $w 2>/dev/null)
  echo "$w | $name | $geo"
done
