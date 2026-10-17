#!/bin/bash
export DISPLAY=:99
import -window root /tmp/screen-now.png
python3 - <<'PY'
from PIL import Image
im = Image.open('/tmp/screen-now.png')
print('size', im.size)
im.save('/mnt/d/AgentPrograms/wechat-bot/wsl/screen-now.png')
PY
ls -la /mnt/d/AgentPrograms/wechat-bot/wsl/screen-now.png
