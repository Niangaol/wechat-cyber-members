#!/bin/bash
PID=$(pgrep -x wechat | head -1)
echo "wechat pid=$PID"
echo "--- cmdline ---"
tr '\0' ' ' < /proc/$PID/cmdline; echo
echo "--- GL/GPU 相关环境变量 ---"
tr '\0' '\n' < /proc/$PID/environ | grep -iE 'gl|gpu|angle|swift|libgl|qt|xcb|egl' || echo "(无)"
echo "--- 启动脚本 ---"
grep -nE 'wechat|exec|env|GL|GPU' /mnt/d/AgentPrograms/wechat-bot/wsl/start-wechat-xvfb.sh 2>/dev/null | head -20
echo "--- stack-main.sh 里的启动段 ---"
grep -nE 'wechat|exec|GL|GPU|DISPLAY' /mnt/d/AgentPrograms/wechat-bot/wsl/stack-main.sh | head -20
