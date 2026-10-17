"""只读：在编辑页截图里量出绿色 Post 按钮的真实矩形（用于校准 publish_button）。"""
import sys
sys.path.insert(0, "/mnt/d/AgentPrograms/wechat-bot/src")
from PIL import Image
import numpy as np

path = sys.argv[1] if len(sys.argv) > 1 else "/mnt/d/AgentPrograms/wechat-bot/shots/moments-2.png"
img = Image.open(path).convert("RGB")
px = np.asarray(img, dtype="int16")
green = (px[:, :, 0] < 140) & (px[:, :, 1] > 150) & (px[:, :, 2] < 160)
rows = green.sum(axis=1)
print("rows with green >= 40:")
start = None
for y, c in enumerate(rows):
    if c >= 40 and start is None:
        start = y
    elif c < 40 and start is not None:
        if y - start >= 10:
            band = green[start:y]
            xs = np.nonzero(band.any(axis=0))[0]
            print("  band y=%d..%d x=%d..%d center=(%d,%d)" % (
                start, y - 1, xs.min(), xs.max(),
                (int(xs.min()) + int(xs.max())) // 2, (start + y - 1) // 2))
        start = None
