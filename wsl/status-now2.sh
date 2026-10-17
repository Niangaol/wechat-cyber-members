#!/bin/bash
export DISPLAY=:99
echo "--- all windows ---"
xdotool search --name ".*" 2>/dev/null | while read -r w; do
  n=$(xdotool getwindowname "$w" 2>/dev/null)
  g=$(xdotool getwindowgeometry "$w" 2>/dev/null | tr '\n' ' ')
  [ -n "$n" ] && echo "$w | $n | $g"
done
echo "--- ledger files ---"
ls -la /home/niangao/.local/state/wechat-bot/ 2>/dev/null
echo "--- ledger report ---"
python3 /mnt/d/AgentPrograms/wechat-bot/wsl/ledger-report.py 2>&1 | tail -20
echo "--- resident log tail ---"
journalctl --user -u wechat-bot -n 25 --no-pager 2>&1 | tail -30
