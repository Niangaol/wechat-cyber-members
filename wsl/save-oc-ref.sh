#!/bin/bash
set -e
SRC="/mnt/c/Users/niangao/.dsh/attachments/v1/objects/97/9786c6236a04a3acc21bfa12456cfb9d034a65515b07f20d772a9e566ee81927"
ls -la "$SRC" 2>/dev/null || { echo "源文件不在（可能已清理）"; exit 1; }
mkdir -p /mnt/d/AgentPrograms/wechat-bot/config/assets
cp "$SRC" /mnt/d/AgentPrograms/wechat-bot/config/assets/oc-reference.png
chmod 644 /mnt/d/AgentPrograms/wechat-bot/config/assets/oc-reference.png
python3 - <<'PY'
import hashlib, json
from PIL import Image
p = "/mnt/d/AgentPrograms/wechat-bot/config/assets/oc-reference.png"
raw = open(p, 'rb').read()
im = Image.open(p)
print(json.dumps({
    'saved': p,
    'bytes': len(raw),
    'sha256': hashlib.sha256(raw).hexdigest()[:16],
    'size': list(im.size),
    'mode': im.mode,
    'matches_original': hashlib.sha256(raw).hexdigest().startswith('9786c6236a04a3ac'),
}, ensure_ascii=False))
PY
