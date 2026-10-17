#!/bin/bash
export DISPLAY=:99
xdotool key Escape
sleep 1.0
import -window 14680150 /mnt/d/AgentPrograms/wechat-bot/wsl/cal-after-esc.png
xdotool key Escape
sleep 1.0
import -window 14680150 /mnt/d/AgentPrograms/wechat-bot/wsl/cal-after-esc2.png
echo done
