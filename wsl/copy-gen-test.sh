#!/bin/bash
cp /home/niangao/.local/state/wechat-bot/media/gen-1792146338.png /mnt/d/AgentPrograms/wechat-bot/wsl/oc-gen-test.png
python3 - <<'PY'
import json
from PIL import Image
im = Image.open('/mnt/d/AgentPrograms/wechat-bot/wsl/oc-gen-test.png')
print(json.dumps({'size': list(im.size), 'mode': im.mode}))
PY
