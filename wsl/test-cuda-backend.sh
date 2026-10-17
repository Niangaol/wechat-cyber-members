#!/bin/bash
SP=/home/niangao/.local/lib/python3.12/site-packages
echo "=== 找库 ==="
find $SP/nvidia -name "libcudart.so.12" -o -name "libcublas.so.12" -o -name "libcublasLt.so.12" 2>/dev/null
echo "=== 拼 LD_LIBRARY_PATH 并测试后端 ==="
export LD_LIBRARY_PATH=$(find $SP/nvidia -name "libcudart.so.12" -o -name "libcublas.so.12" 2>/dev/null | xargs -n1 dirname | sort -u | tr '\n' ':')
echo "LD_LIBRARY_PATH=$LD_LIBRARY_PATH"
cd /opt/uitars/llama-b11669
timeout 40 ./llama-bench --list-devices 2>&1 | tail -8
