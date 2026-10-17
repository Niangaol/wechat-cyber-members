#!/bin/bash
export DISPLAY=:99
echo "--- 堆叠顺序（xdotool search 输出：底→顶）---"
xdotool search --name ".*" 2>/dev/null | while read -r w; do
  n=$(xdotool getwindowname "$w" 2>/dev/null)
  g=$(xdotool getwindowgeometry "$w" 2>/dev/null | tr '\n' ' ')
  [ -n "$n" ] && echo "$w | $n | $g"
done
echo "--- 点 Cancel（窗口内约 600,400 → 绝对 916,613）---"
xdotool mousemove 916 613 click 1
sleep 2
echo "--- Cancel 点击后 Open 窗口还在吗 ---"
xdotool search --name "^Open$" 2>/dev/null || echo "OPEN_DIALOG_GONE (点击送达成功)"
