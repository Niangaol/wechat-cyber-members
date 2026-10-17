#!/bin/bash
export DISPLAY=:99
echo "=== 主窗口子窗口树 ==="
xwininfo -root -tree 2>/dev/null | grep -A30 '14680080' | head -35
