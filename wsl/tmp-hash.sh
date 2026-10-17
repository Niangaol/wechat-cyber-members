#!/bin/bash
python3 -c "
import hashlib
from PIL import Image
for n in ['cal-comment-escaped','cal-textclick']:
    p='/mnt/d/AgentPrograms/wechat-bot/wsl/'+n+'.png'
    print(n, hashlib.sha256(Image.open(p).tobytes()).hexdigest()[:12])
"
