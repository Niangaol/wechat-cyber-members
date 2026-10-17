#!/bin/bash
export DISPLAY=:99
xdotool windowraise 14682371
sleep 0.5
xdotool mousemove 703 426
sleep 0.3
xdotool click 1
sleep 2
import -window root /tmp/after-discard.png
echo done
