#!/bin/bash
export DISPLAY=:99
# 点 Moments 编辑页 Cancel（窗口 14682371 在 353,114；Cancel 相对 345,531）
xdotool mousemove 698 645
sleep 0.3
xdotool click 1
sleep 2
import -window 14682371 /tmp/moments-after-cancel.png
echo done
