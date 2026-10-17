#!/bin/bash
export DISPLAY=:99
echo "--- windows ---"
xdotool search --onlyvisible "" 2>/dev/null | while read wid; do
  name=$(xdotool getwindowname "$wid" 2>/dev/null | head -1)
  geo=$(xdotool getwindowgeometry --shell "$wid" | tr "\n" " ")
  echo "$wid | $name | $geo"
done
echo "--- moments capture ---"
for wid in $(xdotool search --onlyvisible --class wechat); do
  w=$(xdotool getwindowgeometry --shell "$wid" | grep WIDTH=)
  echo "$wid $w"
done
