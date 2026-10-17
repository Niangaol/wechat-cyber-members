#!/bin/bash
export DISPLAY=:99
W=$(xdotool search --name "^Weixin$" 2>/dev/null | head -1)
[ -z "$W" ] && W=$(xdotool search --name "Weixin" 2>/dev/null | head -1)
echo "window=$W"
if [ -n "$W" ]; then
  xdotool windowactivate "$W" 2>/dev/null
  sleep 1
  import -window "$W" /tmp/login-qr.png 2>/dev/null && echo "shot ok $(stat -c%s /tmp/login-qr.png) bytes"
  python3 - <<'PY'
from PIL import Image
im = Image.open('/tmp/login-qr.png')
print('size', im.size)
# 放大 2 倍存一份，方便手机扫
im.resize((im.size[0]*2, im.size[1]*2), Image.LANCZOS).save('/tmp/login-qr-2x.png')
print('2x saved')
PY
fi
