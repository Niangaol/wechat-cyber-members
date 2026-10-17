#!/bin/bash
cd /opt/uitars/llama-b11669
echo "=== libggml-cuda.so 缺失依赖 ==="
ldd ./libggml-cuda.so 2>&1 | grep -i "not found" || echo "(无缺失)"
echo "=== ldd 里 cuda 相关 ==="
ldd ./libggml-cuda.so 2>&1 | grep -iE "cuda|nvidia" | head -10
echo "=== 显式指定后端试试 ==="
timeout 25 ./llama-server --version 2>&1 | head -5
echo "=== 试 CUDA 设备枚举（用 llama-bench 空跑）==="
timeout 30 ./llama-bench --list-devices 2>&1 | head -12
