#!/bin/bash
export DISPLAY=:99
run() { timeout 10 "$@" || echo "CMD_TIMEOUT: $*"; }
DW=$(timeout 10 xdotool search --name "^Open$" 2>/dev/null | head -1)
echo "dialog wid=$DW"
echo "=== 点 Open 按钮（对话框内 596,373）==="
run xdotool mousemove --window $DW 596 373
run xdotool click --window $DW 1
sleep 4
echo "--- 现在的窗口 ---"
for w in $(timeout 10 xdotool search --name ".*" 2>/dev/null); do
  n=$(timeout 5 xdotool getwindowname $w 2>/dev/null)
  g=$(timeout 5 xdotool getwindowgeometry $w 2>/dev/null | grep Geometry | tr -d ' ')
  case "$n" in Weixin|Moments|Open|WeChat|wechat) echo "$w | $n | $g";; esac
done
echo "--- 抓 Moments 窗口 ---"
MW=$(timeout 10 xdotool search --name "^Moments$" 2>/dev/null | head -1)
echo "moments wid=$MW"
[ -n "$MW" ] && { run import -window $MW /tmp/moments-compose.png; cp /tmp/moments-compose.png /mnt/d/AgentPrograms/wechat-bot/wsl/moments-compose.png; echo "shot ok"; }
