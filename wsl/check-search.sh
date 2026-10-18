#!/usr/bin/env bash
# 联网搜索冒烟测试的 bash 入口。实现只有一份：wsl/check-search.py。
# 用法：bash wsl/check-search.sh "国产手柄 推荐"
exec python3 "$(dirname "$0")/check-search.py" "$@"
