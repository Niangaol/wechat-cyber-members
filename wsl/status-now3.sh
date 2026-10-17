#!/bin/bash
export DISPLAY=:99
echo "--- windows ---"
xdotool search --name ".*" 2>/dev/null | while read -r w; do
  n=$(xdotool getwindowname "$w" 2>/dev/null)
  g=$(xdotool getwindowgeometry "$w" 2>/dev/null | tr '\n' ' ')
  [ -n "$n" ] && echo "$w | $n | $g"
done
echo "--- ledger ---"
python3 /mnt/d/AgentPrograms/wechat-bot/wsl/ledger-report.py 2>&1 | tail -10
echo "--- bot log tail ---"
journalctl --user -u wechat-bot -n 6 --no-pager 2>&1 | tail -8
