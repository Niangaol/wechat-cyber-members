#!/bin/bash
export DISPLAY=:99
for w in 12616972 14682343; do
  echo "== $w =="
  xdotool getwindowname $w 2>/dev/null
  import -window $w /mnt/d/AgentPrograms/wechat-bot/wsl/cal-dialog-$w.png 2>&1 && echo shot-ok
done
