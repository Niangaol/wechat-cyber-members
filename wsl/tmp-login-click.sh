#!/bin/bash
export DISPLAY=:99
WID=$(xwininfo -root -tree 2>/dev/null | grep -i weixin | grep -oE "0x[0-9a-f]+" | head -1)
echo "window: $WID"
xwininfo -id "$WID" | grep -E "Width|Height|Absolute"
W=$(xwininfo -id "$WID" | grep "Width:" | grep -oE "[0-9]+" | head -1)
H=$(xwininfo -id "$WID" | grep "Height:" | grep -oE "[0-9]+" | head -1)
WX=$(xwininfo -id "$WID" | grep "Absolute upper-left X" | grep -oE "[0-9]+" | head -1)
WY=$(xwininfo -id "$WID" | grep "Absolute upper-left Y" | grep -oE "[0-9]+" | head -1)
echo "size: ${W}x${H} at ${WX},${WY}"
BX=$((WX + W*140/281)); BY=$((WY + H*271/381))
echo "click at: $BX,$BY"
xdotool mousemove "$BX" "$BY"; sleep 0.5; xdotool click 1
echo "clicked, waiting for main window..."
for i in $(seq 1 30); do
  sleep 3
  INFO=$(xwininfo -root -tree 2>/dev/null | grep -i weixin | head -1)
  W2=$(echo "$INFO" | grep -oE "[0-9]+x[0-9]+" | head -1 | cut -dx -f1)
  echo "[$i] $INFO"
  if [ "${W2:-0}" -gt 600 ] 2>/dev/null; then echo "MAIN_READY"; import -window root /mnt/d/AgentPrograms/wechat-bot/shots/after-login-$(date +%H%M%S).png; exit 0; fi
done
echo "TIMEOUT"
import -window root /mnt/d/AgentPrograms/wechat-bot/shots/after-login-timeout-$(date +%H%M%S).png
