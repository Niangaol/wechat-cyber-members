#!/bin/bash
echo "=== pip 可用? ==="
which pip3 python3 && python3 -V
echo "=== 安装 CUDA 12 运行时库（pip 轮子）==="
pip3 install --quiet --break-system-packages nvidia-cuda-runtime-cu12 nvidia-cublas-cu12 2>&1 | tail -5
echo "=== 找到的库 ==="
python3 -c "import nvidia; print(nvidia.__path__[0])" 2>/dev/null
find /usr/lib/python3*/dist-packages/nvidia /usr/local/lib/python3*/dist-packages/nvidia ~/.local/lib/python3*/site-packages/nvidia -name "libcudart.so.12" -o -name "libcublas.so.12" 2>/dev/null | head -6
