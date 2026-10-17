#/bin/bash
export DISPLAY=:99
WID=$(xdotool search --onlyvisible --name "^Moments$" | head -1)
if [ -z "$WID" ]; then echo NO_MOMENTS; exit 0; fi
echo "wid=$WID"
xdotool windowraise "$WID"
xdotool windowfocus "$WID"
sleep 0.5
xdotool mousemove 698 601
sleep 0.3
xdotool click 1
sleep 2
# 若弹出 Save this draft?，点 Discard（屏幕绝对 703,426）
xdotool mousemove 703 426
sleep 0.3
xdotool click 1
sleep 2
import -window root /tmp/after-cancel3.png
echo done
