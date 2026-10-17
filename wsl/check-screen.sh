#!/bin/bash
export DISPLAY=:99
echo "--- 所有窗口（含无名）---"
xdotool search --name ".*" 2>/dev/null | while read -r w; do
  echo "wid=$w name=[$(xdotool getwindowname $w 2>/dev/null)]"
done
echo "--- 精确搜 Weixin ---"
xdotool search --name "^Weixin$" 2>/dev/null || echo "NO_WEIXIN"
echo "--- 根窗口截图 ---"
import -window root /tmp/root.png 2>&1 && echo "ok $(stat -c%s /tmp/root.png)"
cp /tmp/root.png /mnt/d/AgentPrograms/wechat-bot/wsl/screen-root.png
echo "--- wechat 日志尾部 ---"
tail -5 /tmp/wechat-xvfb.log 2>/dev/null || echo "no log"
