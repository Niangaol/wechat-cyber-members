#!/bin/bash
export DISPLAY=:99
W=14680080
run() { timeout 12 "$@" || echo "TIMEOUT: $*"; }
echo "=== 回测试群（列表第1行）==="
run xdotool mousemove 273 141
run xdotool click 1
sleep 2.5
import -window $W /tmp/g1.png
echo "=== 点输入框里的图片预览（找删除按钮）==="
run xdotool mousemove 600 572
sleep 0.8
import -window $W /tmp/g2.png
cp /tmp/g2.png /mnt/d/AgentPrograms/wechat-bot/wsl/preview-hover.png
echo "=== 截预览区放大看有无 × ==="
python3 - <<'PY'
from PIL import Image
im = Image.open('/tmp/g2.png').convert('RGB')
im.crop((283, 535, 700, 615)).resize((835, 160), Image.LANCZOS).save('/mnt/d/AgentPrograms/wechat-bot/wsl/preview-zoom.png')
print('zoom saved')
PY
