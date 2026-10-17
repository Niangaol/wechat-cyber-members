#!/bin/bash
echo "=== 停掉 CPU 版服务 ==="
pkill -f "llama-server.*8088" 2>/dev/null; sleep 3
pgrep -f "llama-server" || echo "(已停)"
echo "=== 带 CUDA 重启 ==="
bash /mnt/d/AgentPrograms/wechat-bot/wsl/start-uitars-server.sh
