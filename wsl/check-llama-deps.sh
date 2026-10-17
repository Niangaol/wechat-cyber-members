#!/bin/bash
cd /opt/uitars/llama-b11669
echo "=== 目录内容 ==="
ls
echo "=== llama-server 缺失的共享库 ==="
ldd ./llama-server 2>&1 | grep -i "not found" || echo "(无缺失，依赖全齐)"
echo "=== CUDA 相关库 ==="
ldd ./llama-server 2>&1 | grep -iE "cuda|nvidia|cublas|cudart" | head -10
