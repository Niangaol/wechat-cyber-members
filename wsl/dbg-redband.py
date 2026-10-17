"""只读：在整屏截图里量失败红条的位置与红色像素数。"""
import sys
import numpy as np
from PIL import Image

path = sys.argv[1] if len(sys.argv) > 1 else "/mnt/d/AgentPrograms/wechat-bot/shots/native-path.png"
img = Image.open(path).convert("RGB")
px = np.asarray(img, dtype="int16")
red = (px[:, :, 0] > 150) & (px[:, :, 1] < 90) & (px[:, :, 2] < 90)
print("total red px:", int(red.sum()))
rows = red.sum(axis=1)
start = None
for y, c in enumerate(rows):
    if c >= 30 and start is None:
        start = y
    elif c < 30 and start is not None:
        if y - start >= 8:
            xs = np.nonzero(red[start:y].any(axis=0))[0]
            print("band y=%d..%d x=%d..%d red=%d" % (
                start, y - 1, xs.min(), xs.max(), int(red[start:y].sum())))
        start = None
