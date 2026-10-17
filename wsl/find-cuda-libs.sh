#!/bin/bash
echo "=== pip 列表里的 nvidia 包 ==="
python3 -m pip list --break-system-packages 2>/dev/null | grep -i nvidia
echo "=== 全盘找 libcudart ==="
find /usr/local/lib/python3.12/dist-packages /usr/lib/python3/dist-packages -name "libcudart*" 2>/dev/null | head -5
echo "=== nvidia 目录结构 ==="
ls /usr/local/lib/python3.12/dist-packages/nvidia/ 2>/dev/null
ls /usr/local/lib/python3.12/dist-packages/nvidia/cuda_runtime/lib/ 2>/dev/null | head -5
