#!/bin/bash
echo "--- Linux mentions in context"
grep -oiE '.{60}linux.{100}' /tmp/umi.html | sed 's/<[^>]*>//g' | head -8
echo
echo "--- all download links"
grep -oE '/hiroi-sora/Umi-OCR/releases/download/[^"]+' /tmp/umi.html | sort -u
