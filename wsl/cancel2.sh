#/bin/bash
export DISPLAY=:99
xdotool windowactivate 14682371
sleep 1
xdotool mousemove 698 645
sleep 0.3
xdotool click 1
sleep 2
import -window 14682371 /tmp/m1.png
# 若还在，Escape 兜底
if xdotool getwindowname 14682371 >/dev/null 2>&1; then
  xdotool key --window 14682371 --clearmodifiers Escape
  sleep 1
  xdotool key --clearmodifiers Escape
  sleep 2
  import -window 14682371 /tmp/m2.png
fi
echo done
