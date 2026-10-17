#!/bin/bash
export DISPLAY=:99
xwininfo -id 14682366 | grep -E "Absolute|Width|Height"
import -window 14682366 /mnt/d/AgentPrograms/wechat-bot/wsl/cal-sns-menu.png
import -window root /mnt/d/AgentPrograms/wechat-bot/wsl/cal-sns-menu-root.png
echo done
