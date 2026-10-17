#!/bin/bash
# 抓 Umi-OCR 发布页并列出资产文件名（GitHub 需直连，不能走代理）
curl -sL --noproxy '*' --max-time 30 -A 'Mozilla/5.0'   https://github.com/hiroi-sora/Umi-OCR/releases/tag/v2.1.5 -o /tmp/umi.html
echo "html_bytes=$(stat -c %s /tmp/umi.html 2>/dev/null)"
echo "--- assets"
grep -oE 'Umi-OCR[^"]*.(7z|zip|exe)' /tmp/umi.html | sort -u
echo "--- platform hints"
grep -oiE '(Windows|Linux|Win7|Win10|Win11|x64|arm64)' /tmp/umi.html | sort | uniq -c | sort -rn | head
