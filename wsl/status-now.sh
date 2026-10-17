#!/bin/bash
cd /mnt/d/AgentPrograms/wechat-bot
python3 -m py_compile wsl/verify-batch-ocr.py && echo COMPILE_OK
echo "--- windows ---"
xdotool search --onlyvisible --name "." 2>/dev/null | while read -r w; do
  n=$(xdotool getwindowname "$w" 2>/dev/null)
  g=$(xdotool getwindowgeometry "$w" 2>/dev/null | tr '\n' ' ')
  [ -n "$n" ] && echo "$w | $n | $g"
done
echo "--- wechat proc ---"
pgrep -a -f wechat | head -5
echo "--- stack ---"
systemctl --user is-active wechat-stack wechat-bot 2>&1
echo "--- ledger ---"
cat /home/niangao/.local/state/wechat-bot/STOP 2>/dev/null || echo "no STOP file"
python3 /home/niangao/.local/state/wechat-bot/ledger-report.py 2>/dev/null | tail -15 || true
