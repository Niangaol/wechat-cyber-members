#!/bin/bash
export DISPLAY=:99
W=16777219
import -window $W /tmp/moments.png 2>/tmp/imperr.txt
echo "rc=$?"
cat /tmp/imperr.txt
ls -la /tmp/moments.png 2>/dev/null
xwininfo -id $W 2>&1 | head -12
