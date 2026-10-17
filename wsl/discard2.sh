#/bin/bash
export DISPLAY=:99
WID=$(xdotool search --onlyvisible --name "^Moments$" | head -1)
xdotool windowraise "$WID"
sleep 0.4
xdotool mousemove 703 426
sleep 0.3
xdotool click 1
sleep 2
import -window root /tmp/after-discard2.png
echo done
