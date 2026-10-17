#!/bin/bash
export DISPLAY=:99
W=14680080
sleep 2
import -window $W /tmp/final.png
python3 - <<'PY'
import subprocess, json
from PIL import Image
im = Image.open('/tmp/final.png').convert('RGB')
# 列表第1行（测试群）区域
row = im.crop((95, 95, 350, 150))
row.save('/tmp/row1.png')
out = subprocess.run(['tesseract','/tmp/row1.png','stdout','-l','chi_sim+eng','--psm','6'],
                     capture_output=True, text=True, timeout=60).stdout
# 输入框最终状态
zone = im.crop((283, 600, 945, 660)).convert('L')
n = sum(1 for v in zone.getdata() if v < 235)
print(json.dumps({'row1_text': out.strip()[:80],
                  'input_nonwhite': n,
                  'input_clean': n < 500}, ensure_ascii=False))
PY
cp /tmp/final.png /mnt/d/AgentPrograms/wechat-bot/wsl/input-final-clean.png
