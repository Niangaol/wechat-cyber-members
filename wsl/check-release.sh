#!/bin/bash
cd /mnt/d/AgentPrograms/wechat-bot
echo "=== syntax ==="
python3 -m py_compile wsl/calibrate-moments.py wsl/moment-release.py src/moment_release.py && echo COMPILE_OK
echo "=== calibrate --show ==="
python3 wsl/calibrate-moments.py --show
echo "=== moment-release --list ==="
python3 wsl/moment-release.py --list
echo "=== moment-release --dry-run (无令牌应拒绝) ==="
python3 wsl/moment-release.py --dry-run; echo "rc=$?"
