#!/bin/bash
curl -sL --noproxy '*' --max-time 30 -A 'Mozilla/5.0'   https://raw.githubusercontent.com/hiroi-sora/PaddleOCR-json/release/1.4.1/cpp/README-linux.md -o /tmp/pj-linux.md
echo "bytes=$(stat -c %s /tmp/pj-linux.md)"
echo "=== 前 70 行"
head -70 /tmp/pj-linux.md
