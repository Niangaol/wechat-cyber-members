#!/bin/bash
export DISPLAY=:99
echo "--- windows ---"
xdotool search --name ".*" 2>/dev/null | while read -r w; do
  n=$(xdotool getwindowname "$w" 2>/dev/null)
  g=$(xdotool getwindowgeometry "$w" 2>/dev/null | tr '\n' ' ')
  [ -n "$n" ] && echo "$w | $n | $g"
done
echo "--- active window ---"
xdotool getactivewindow getwindowname 2>/dev/null
xdotool getwindowgeometry $(xdotool getactivewindow) 2>/dev/null | tr '\n' ' '; echo
