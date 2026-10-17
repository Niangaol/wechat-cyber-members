#!/bin/bash
echo "--- media dir ---"
ls -la /home/niangao/.local/state/wechat-bot/media/ 2>&1
echo "--- callers of imagegen ---"
grep -rn "imagegen" /mnt/d/AgentPrograms/wechat-bot/src /mnt/d/AgentPrograms/wechat-bot/wsl /mnt/d/AgentPrograms/wechat-bot/test_*.py 2>/dev/null | grep -v "src/imagegen.py:" | head -20
echo "--- publisher image usage ---"
grep -rn "with_image\|image" /mnt/d/AgentPrograms/wechat-bot/src/publisher.py 2>/dev/null | head -20
echo "--- ls src ---"
ls /mnt/d/AgentPrograms/wechat-bot/src/
