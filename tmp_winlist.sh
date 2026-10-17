#!/bin/bash
export DISPLAY=:99
ids=$( { xdotool search --class wechat 2>/dev/null; xdotool search --name '.*' 2>/dev/null; } | sort -u )
for id in $ids; do
  name=$(xdotool getwindowname "$id" 2>/dev/null)
  cls=$(xprop -id "$id" WM_CLASS 2>/dev/null | head -1)
  geo=$(xdotool getwindowgeometry --shell "$id" 2>/dev/null | grep -E 'WIDTH|HEIGHT' | tr '\n' ' ')
  echo "id=$id name=[$name] $cls $geo"
done
