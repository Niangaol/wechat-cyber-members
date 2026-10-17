#!/bin/bash
export DISPLAY=:99
import -window 14680080 /tmp/tb.png
python3 - <<'PY'
import json
from PIL import Image
im = Image.open('/tmp/tb.png').convert('RGB')
px = im.load()
# 工具栏区域：绝对 y 585-615；x 从 283（内容区左缘）扫到 520
y1, y2 = 588, 612
cols = []
for x in range(285, 520):
    cnt = 0
    for y in range(y1, y2):
        r, g, b = px[x, y]
        # 图标是深色线条（<150），背景是浅灰(~237)
        if r < 160 and g < 160 and b < 160:
            cnt += 1
    cols.append((x, cnt))
# 按列聚类找图标簇
clusters, cur = [], []
for x, c in cols:
    if c >= 3:
        cur.append(x)
    else:
        if len(cur) >= 5:
            clusters.append(cur)
        cur = []
if len(cur) >= 5:
    clusters.append(cur)
out = []
for cl in clusters:
    cx = (cl[0] + cl[-1]) // 2
    # 该簇的垂直范围
    ys = [y for y in range(y1, y2)
          for x in cl if px[x, y][0] < 160 and px[x, y][1] < 160 and px[x, y][2] < 160]
    out.append({'cx': cx, 'width': cl[-1]-cl[0],
                'cy': (min(ys)+max(ys))//2 if ys else None})
print(json.dumps({'toolbar_icons': out}, ensure_ascii=False))
PY
