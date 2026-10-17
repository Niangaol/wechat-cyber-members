#!/bin/bash
export DISPLAY=:99
echo "wechat_window: $(xwininfo -root -tree 2>/dev/null | grep -c Weixin)"
echo "stack: $(systemctl --user is-active wechat-stack)"
echo "bot: $(systemctl --user is-active wechat-bot)"
echo "novnc: $(ss -tln | grep -c 6080)"
echo "radium: $(pgrep -x RadiumWMPF | wc -l)"
