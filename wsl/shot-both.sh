#!/bin/bash
export DISPLAY=:99
import -window 14680080 /tmp/main.png 2>/dev/null && echo "main $(stat -c%s /tmp/main.png)"
import -window 16777219 /tmp/wechat2.png 2>/dev/null && echo "wechat2 $(stat -c%s /tmp/wechat2.png)"
cp /tmp/main.png /mnt/d/AgentPrograms/wechat-bot/wsl/shot-main-now.png
cp /tmp/wechat2.png /mnt/d/AgentPrograms/wechat-bot/wsl/shot-wechat2.png
echo done
