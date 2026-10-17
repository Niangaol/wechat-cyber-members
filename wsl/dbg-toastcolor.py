"""只读：采样失败红条的真实颜色。"""
import numpy as np
from PIL import Image
img = Image.open("/mnt/d/AgentPrograms/wechat-bot/shots/native-path.png").convert("RGB")
px = np.asarray(img)
for pt in [(640, 478), (600, 478), (700, 478), (637, 530), (600, 530)]:
    x, y = pt
    print(pt, px[y, x])
reg = px[455:550, 540:740].reshape(-1, 3)
uniq, counts = np.unique(reg, axis=0, return_counts=True)
order = np.argsort(-counts)[:8]
print("top colors in toast region:")
for i in order:
    print("  ", uniq[i], int(counts[i]))
