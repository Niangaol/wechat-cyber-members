#!/bin/bash
# 关闭僵尸 Moments 窗口并列出剩余可见 wechat 类窗口的几何。
export DISPLAY=:99
xdotool windowclose 0xe008db 2>/dev/null
sleep 2
xdotool search --onlyvisible --class wechat | while read wid; do
  geo=$(xdotool getwindowgeometry --shell "$wid" | tr "\n" " ")
  echo "wid=$wid $geo"
done
