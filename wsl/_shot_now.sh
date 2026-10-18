#!/usr/bin/env bash
cd /mnt/d/AgentPrograms/wechat-bot
export DISPLAY=:99
timeout 40 python3 -c "
import sys; sys.path.insert(0,'src')
from screen import find_wechat_windows, screenshot_window
w = find_wechat_windows(':99')
frame = w.get('frame') or w.get('client')
print('窗口:', frame and (frame['id'], frame['w'], frame['h'], frame['title']))
if frame:
    screenshot_window(frame['id'], 'wsl/_shot_now.png', ':99')
    print('已截图')
" 2>&1
ls -la wsl/_shot_now.png 2>&1 | head -2
