#!/bin/bash
echo "=== 1. 现成 llama.cpp? ==="
ls /usr/local/bin/llama* /usr/bin/llama* 2>/dev/null; find /usr /opt -maxdepth 3 -name "llama-server" 2>/dev/null | head -3; echo "(以上为空则没有)"
echo "=== 2. CUDA 痕迹 ==="
ls -d /usr/local/cuda* 2>/dev/null; dpkg -l 2>/dev/null | grep -iE "cuda|nvidia" | awk '{print $2}' | head -8; echo "---"
ls /usr/lib/wsl/lib/ 2>/dev/null | head -10
echo "=== 3. Vulkan ==="
dpkg -l 2>/dev/null | grep -i vulkan | awk '{print $2}' | head -5
ls /usr/lib/x86_64-linux-gnu/libvulkan* /usr/lib/x86_64-linux-gnu/libnvidia* 2>/dev/null | head -5
echo "=== 4. 编译工具 ==="
which cmake gcc g++ make ccache 2>/dev/null
echo "=== 5. 网络（GitHub 直连）==="
timeout 12 curl -sI --noproxy '*' https://github.com 2>&1 | head -3
timeout 12 curl -s --noproxy '*' -o /dev/null -w "github release api: %{http_code}
" https://api.github.com/repos/ggml-org/llama.cpp/releases/latest 2>&1
echo "=== 6. 磁盘与内存 ==="
free -g | head -2
df -h /home /mnt/d | tail -2
