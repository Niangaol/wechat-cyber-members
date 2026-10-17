#!/bin/bash
export DISPLAY=:99
MW=14680193
python3 - <<'PY'
import io, json, subprocess
from PIL import Image
raw = subprocess.run(['import','-window','14680193','png:-'],capture_output=True,timeout=30).stdout
im = Image.open(io.BytesIO(raw)).convert('RGB')
w,h = im.size
px = im.load()
# 找底部两个按钮：灰色 Cancel（非绿）和绿色 Finish；按钮是有边框的圆角矩形
# 扫描底部 25% 区域的按钮底色
from collections import Counter
cand = Counter()
for y in range(int(h*0.75), h):
    for x in range(0, w, 2):
        r,g,b = px[x,y]
        # 按钮灰约 (240,240,240) 带边框
        if 225 <= r <= 250 and 225 <= g <= 250 and 225 <= b <= 250:
            cand[x] += 1
# 按 x 聚类找两个按钮
xs = sorted(cand)
groups, cur = [], []
for x in xs:
    if cur and x - cur[-1] > 20:
        if len(cur) > 30: groups.append(cur)
        cur = []
    cur.append(x)
if len(cur) > 30: groups.append(cur)
btns = [{'cx': (g[0]+g[-1])//2, 'w': g[-1]-g[0]} for g in groups]
print(json.dumps({'size':[w,h],'buttons':btns}, ensure_ascii=False))
PY
