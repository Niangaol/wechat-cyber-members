#!/bin/bash
export DISPLAY=:99
xwininfo -root -tree 2>/dev/null > /tmp/tree.txt
# 找 Weixin 主窗（0xe00010）之后的 56 个子窗口行
grep -n '0xe00010 "Weixin"' /tmp/tree.txt
START=$(grep -n '0xe00010 "Weixin"' /tmp/tree.txt | cut -d: -f1)
tail -n +$START /tmp/tree.txt | head -58
