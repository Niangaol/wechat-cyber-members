#!/bin/bash
pgrep -f llama-server >/dev/null && echo "SERVER_UP" || echo "SERVER_DOWN"
cd /mnt/d/AgentPrograms/wechat-bot
timeout 600 python3 wsl/uitars-agent.py "点击输入框工具栏最左边的圆形笑脸图标，打开表情/贴图面板" --crop 290,585,250,40 --max-steps 3 2>&1
