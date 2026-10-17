#!/bin/bash
cd /opt/uitars
tar xzf llama-cuda.tar.gz && ls -la
echo "=== 找 llama-server ==="
find . -name "llama-server" -o -name "llama-cli" | head -5
