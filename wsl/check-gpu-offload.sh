#!/bin/bash
echo "=== CUDA/GPU 卸载情况 ==="
grep -iE "cuda|gpu|vulkan|offload|layers|VRAM|device" /tmp/uitars-server/server.log | head -20
echo "=== 显存占用 ==="
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader 2>/dev/null | head -3
