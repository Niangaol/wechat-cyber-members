#!/bin/bash
# 抓 PaddleOCR-json（Umi-OCR 的 OCR 引擎）发布页，找 Linux 资产
curl -sL --noproxy '*' --max-time 30 -A 'Mozilla/5.0'   https://github.com/hiroi-sora/PaddleOCR-json/releases -o /tmp/pj.html
echo "bytes=$(stat -c %s /tmp/pj.html 2>/dev/null)"
echo "--- Linux 相关资产"
grep -oE 'PaddleOCR-json[^"]*Linux[^"]*.(7z|zip|tar.xz)' /tmp/pj.html | sort -u | head -20
echo "--- 所有发行标签"
grep -oE '/hiroi-sora/PaddleOCR-json/releases/tag/[^"]+' /tmp/pj.html | sort -u | head -10
