#!/bin/bash
echo "=== pip 安装 CUDA 12 库 ==="
python3 -m pip install --quiet --break-system-packages nvidia-cuda-runtime-cu12 nvidia-cublas-cu12 2>&1 | tail -3
echo "=== 库位置 ==="
SP=$(python3 -c "import site; print(site.getsitepackages()[0])" 2>/dev/null)
echo "site-packages: $SP"
find "$SP/nvidia" -name "libcudart.so.12" -o -name "libcublas.so.12" -o -name "libcublasLt.so.12" 2>/dev/null | head -6
