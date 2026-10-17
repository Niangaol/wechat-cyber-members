#!/bin/bash
export DISPLAY=:99
W=$(xdotool search --name "^Moments$" 2>/dev/null | head -1)
echo "moments window: $W"
import -window $W /tmp/moments-win.png 2>&1 && echo "OK $(stat -c%s /tmp/moments-win.png) bytes"
python3 - <<'PY'
import json
from PIL import Image
im = Image.open('/tmp/moments-win.png').convert('RGB')
px = list(im.getdata())
n = len(px)
print(json.dumps({'size': list(im.size),
                  'avg_brightness': round(sum(sum(p) for p in px[::53])/(3*len(px[::53])),1),
                  'pure_black_pct': round(100*sum(1 for p in px if p==(0,0,0))/n,1),
                  'light_pct': round(100*sum(1 for p in px if sum(p)>600)/n,1)}))
PY
cp /tmp/moments-win.png /mnt/d/AgentPrograms/wechat-bot/wsl/moments-window.png
