#!/bin/bash
# WSL 内起本地 UI-TARS VLM（调用 Windows 侧 llama-server.exe，模型在 D 盘）
LLAMA="/mnt/c/Users/niangao/AppData/Local/Microsoft/WinGet/Packages/ggml.llamacpp_Microsoft.Winget.Source_8wekyb3d8bbwe/llama-server.exe"
MODELS="D:/AgentPrograms/ui-tars-mcp/models"
if curl -s --max-time 3 http://127.0.0.1:8088/health > /dev/null 2>&1; then
    echo "VLM_ALREADY_RUNNING"
    exit 0
fi
setsid nohup "$LLAMA" \
    -m "$MODELS/UI-TARS-1.5-7B.Q4_K_M.gguf" \
    --mmproj "$MODELS/UI-TARS-1.5-7B.mmproj-Q8_0.gguf" \
    --port 8088 --host 127.0.0.1 \
    -c 16384 --image-min-tokens 1024 --n-predict 512 \
    > /tmp/vlm.log 2>&1 < /dev/null &
disown 2>/dev/null
echo "VLM_STARTING"
# 等模型就绪（最多 120 秒）
for i in $(seq 1 24); do
    sleep 5
    if curl -s --max-time 3 http://127.0.0.1:8088/health > /dev/null 2>&1; then
        echo "VLM_READY after $((i*5))s"
        exit 0
    fi
done
echo "VLM_TIMEOUT"
tail -5 /tmp/vlm.log
