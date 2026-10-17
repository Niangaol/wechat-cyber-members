#!/bin/bash
# WSL 内的 UI-TARS 本地视觉模型服务（llama.cpp CUDA 版，RTX 5070 Ti）
# 与 Windows 侧 start-local-vlm.sh 同参数；区别：跑在 WSL，看 Xvfb :99 的屏
set -e
DIR=/opt/uitars
BIN=$DIR/llama-b11669/llama-server
MODEL=$DIR/models/UI-TARS-1.5-7B.Q4_K_M.gguf
MMPROJ=$DIR/models/UI-TARS-1.5-7B.mmproj-Q8_0.gguf
PORT=${UITARS_PORT:-8088}
export DISPLAY=${DISPLAY:-:99}
# pip 装的 CUDA 12 运行时（libcudart/libcublas）；驱动 libcuda.so.1 由 /usr/lib/wsl/lib 提供
NVIDIA_LIBS=$(find /home/niangao/.local/lib/python3.12/site-packages/nvidia \
              -name "libcudart.so.12" -o -name "libcublas.so.12" 2>/dev/null \
              | xargs -n1 dirname | sort -u | tr '\n' ':')
export LD_LIBRARY_PATH="${NVIDIA_LIBS}${LD_LIBRARY_PATH:-}"

for f in "$BIN" "$MODEL" "$MMPROJ"; do
  [ -f "$f" ] || { echo "缺少文件: $f"; exit 1; }
done

if curl -s -o /dev/null --max-time 3 "http://127.0.0.1:$PORT/v1/models"; then
  echo "ALREADY_RUNNING port=$PORT"
  exit 0
fi

echo "启动 WSL UI-TARS VLM 服务 http://127.0.0.1:$PORT/v1"
echo "  模型:   $MODEL"
echo "  后端:   CUDA (RTX 5070 Ti)"
mkdir -p /tmp/uitars-server
nohup "$BIN" \
  -m "$MODEL" \
  --mmproj "$MMPROJ" \
  --host 127.0.0.1 \
  --port "$PORT" \
  -ngl 99 \
  -c 16384 \
  --image-min-tokens 1024 \
  --flash-attn on \
  --chat-template chatml \
  --temp 0 \
  --top-p 0.7 \
  --no-warmup \
  > /tmp/uitars-server/server.log 2>&1 &
echo "pid=$!"
for i in $(seq 1 90); do
  sleep 2
  if curl -s -o /dev/null --max-time 3 "http://127.0.0.1:$PORT/v1/models"; then
    echo "READY after about $((i*2)) seconds"
    curl -s "http://127.0.0.1:$PORT/v1/models" | head -c 300
    echo
    exit 0
  fi
done
echo "TIMEOUT: not ready in 180s, see /tmp/uitars-server/server.log"
tail -20 /tmp/uitars-server/server.log
exit 1
