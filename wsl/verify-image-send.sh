#!/bin/bash
# 图片发送机制验收：执行到"预览验证"为止，Escape 取消，绝不发送
export DISPLAY=:99
W=14680080
IMG=/tmp/oc-thumb.png
run() { timeout 12 "$@" || echo "TIMEOUT: $*"; }

echo "=== 1. 确认在测试群（标题 OCR）==="
import -window $W /tmp/s1.png
python3 - <<'PY'
import subprocess, json
out = subprocess.run(['tesseract','/tmp/s1.png','stdout','-l','chi_sim+eng','--psm','6'],
                     capture_output=True, text=True, timeout=60).stdout
ok = '聊天测试群' in out
print(json.dumps({'in_test_group': ok}, ensure_ascii=False))
PY

echo "=== 2. 输入框无草稿检查（283,605,945,654）==="
python3 - <<'PY'
import subprocess, json
from PIL import Image
im = Image.open('/tmp/s1.png').convert('RGB')
zone = im.crop((283, 605, 945, 654))
zone.save('/tmp/inputzone.png')
out = subprocess.run(['tesseract','/tmp/inputzone.png','stdout','-l','chi_sim+eng','--psm','6'],
                     capture_output=True, text=True, timeout=60).stdout
print(json.dumps({'draft_text': out.strip()[:60]}, ensure_ascii=False))
PY

echo "=== 3. xclip 写 image/png 到剪贴板 ==="
xclip -selection clipboard -t image/png -i $IMG
sleep 1
echo "clipboard targets: $(xclip -selection clipboard -t TARGETS -o 2>/dev/null | tr '\n' ' ')"

echo "=== 4. ctrl+v 粘贴到输入框 ==="
run xdotool key --window $W --clearmodifiers ctrl+v
sleep 2.5

echo "=== 5. 预览区像素验证（283,540,945,605 非白像素）==="
import -window $W /tmp/s2.png
cp /tmp/s2.png /mnt/d/AgentPrograms/wechat-bot/wsl/image-preview-proof.png
python3 - <<'PY'
import json
from PIL import Image
im = Image.open('/tmp/s2.png').convert('RGB')
zone = im.crop((283, 540, 945, 605)).convert('L')
nonwhite = sum(1 for v in zone.getdata() if v < 235)
print(json.dumps({'preview_nonwhite_px': nonwhite,
                  'threshold': 500,
                  'preview_has_image': nonwhite >= 500}, ensure_ascii=False))
PY

echo "=== 6. Escape 取消（不发送！）==="
run xdotool key --window $W --clearmodifiers Escape
sleep 1.5
import -window $W /tmp/s3.png
echo "=== 7. 复查输入框已清空 ==="
python3 - <<'PY'
import subprocess, json
from PIL import Image
im = Image.open('/tmp/s3.png').convert('RGB')
zone = im.crop((283, 605, 945, 654))
zone.save('/tmp/inputzone2.png')
out = subprocess.run(['tesseract','/tmp/inputzone2.png','stdout','-l','chi_sim+eng','--psm','6'],
                     capture_output=True, text=True, timeout=60).stdout
print(json.dumps({'input_after_escape': out.strip()[:60]}, ensure_ascii=False))
PY
