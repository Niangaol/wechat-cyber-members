#/bin/bash
export DISPLAY=:99
W=14682371
xdotool windowraise $W
sleep 0.5
xdotool windowactivate $W 2>/dev/null
sleep 0.5
xdotool mousemove 698 645
sleep 0.3
xdotool click 1
sleep 2
import -window $W /tmp/m3.png
import -window root /tmp/root3.png
# 兜底：--window 直送点击 Cancel
xdotool mousemove --window $W 345 531
sleep 0.3
xdotool click --window $W 1
sleep 2
import -window $W /tmp/m4.png
echo done
