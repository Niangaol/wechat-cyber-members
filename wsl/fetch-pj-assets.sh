#!/bin/bash
for tag in v1.4.1 v1.3.1; do
  echo "=== $tag"
  curl -sL --noproxy '*' --max-time 30 -A 'Mozilla/5.0'     "https://github.com/hiroi-sora/PaddleOCR-json/releases/tag/$tag" -o /tmp/pj-$tag.html
  grep -oE '/hiroi-sora/PaddleOCR-json/releases/download/[^"]+' /tmp/pj-$tag.html | sort -u
done
echo "=== README 中 Linux 构建说明"
curl -sL --noproxy '*' --max-time 30 -A 'Mozilla/5.0'   https://raw.githubusercontent.com/hiroi-sora/PaddleOCR-json/main/README.md -o /tmp/pj-readme.md
grep -niE 'linux|ubuntu|debian|编译|build' /tmp/pj-readme.md | head -20
