"""只读：按颜色识别主窗口侧边栏图标（绿色=聊天，其余按顺序）。"""
import numpy as np
from PIL import Image

img = Image.open("/mnt/d/AgentPrograms/wechat-bot/shots/panel-reset.png").convert("RGB")
px = np.asarray(img, dtype="int16")
band = px[60:400, 14:52]
r, g, b = band[:, :, 0], band[:, :, 1], band[:, :, 2]
gray = band.mean(axis=2)
rows = (gray < 235).sum(axis=1)
runs, start = [], None
for i, v in enumerate(rows):
    if v >= 3 and start is None:
        start = i
    elif v < 3 and start is not None:
        if i - start >= 8:
            runs.append((start + 60, i + 60))
        start = None
if start is not None:
    runs.append((start + 60, len(rows) + 60))
for a, bb in runs:
    seg = px[a:bb, 14:52]
    green = ((seg[:, :, 1] > 140) & (seg[:, :, 0] < 120)).sum()
    print("band y=%d..%d center=%d green_px=%d" % (a, bb, (a + bb) // 2, int(green)))
