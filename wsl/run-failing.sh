#!/bin/bash
cd /mnt/d/AgentPrograms/wechat-bot
python3 -m unittest test_send_binding test_integration 2>&1 | grep -B1 -A 14 -E "^(FAIL|ERROR):" | head -100
