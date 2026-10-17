#!/bin/bash
export DISPLAY=:99
echo "=== 点笑脸精确位 (312,605) ==="
xdotool mousemove 312 605 click 1
sleep 2.5
echo "--- 新窗口? ---"
for w in $(xdotool search --name ".*" 2>/dev/null); do
  n=$(xdotool getwindowname $w 2>/dev/null)
  case "$n" in Weixin|Moments|Open|Chat*|*Emoji*|*Sticker*) echo "$w | $n";; esac
done
import -window root /tmp/smile4.png
cp /tmp/smile4.png /mnt/d/AgentPrograms/wechat-bot/wsl/smile-precise.png
echo "--- 主窗口工具栏下方变化检测 ---"
python3 - <<'PY'
import json
from PIL import Image
im = Image.open('/tmp/smile4.png').convert('RGB')
main = im.crop((396, 585, 1058, 740))
px = list(main.getdata())
dark = sum(1 for p in px if sum(p) < 200)
print(json.dumps({'below_toolbar_nonbg_px': dark, 'panel_maybe_open': dark > 2000}, ensure_ascii=False))
PY
