#!/bin/bash
for i in $(seq 1 40); do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://127.0.0.1:8088/v1/models 2>/dev/null)
  [ "$CODE" = "200" ] && { echo "READY after ~$((i*3))s"; break; }
  sleep 3
done
echo "=== GPU 卸载日志 ==="
grep -iE "cuda|offload|layers|VRAM|repeating layers" /tmp/uitars-server/server.log | head -12
echo "=== 显存占用 ==="
nvidia-smi --query-gpu=memory.used --format=csv,noheader
nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader | head -3
