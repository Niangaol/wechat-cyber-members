#!/bin/bash
export DISPLAY=:99
xwininfo -id 14682348 | grep -E "Absolute|Width|Height"
import -window 14682348 /mnt/d/AgentPrograms/wechat-bot/wsl/cal-rclick-menu.png
echo done
