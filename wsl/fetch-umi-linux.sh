#!/bin/bash
# 抓 Umi-OCR 官方 Linux 运行时的 README（GitHub 直连）
curl -sL --noproxy '*' --max-time 30 -A 'Mozilla/5.0'   https://raw.githubusercontent.com/hiroi-sora/Umi-OCR_runtime_linux/main/README.md -o /tmp/umi-linux.md
echo "bytes=$(stat -c %s /tmp/umi-linux.md 2>/dev/null)"
echo "--- 前 80 行"
head -80 /tmp/umi-linux.md
