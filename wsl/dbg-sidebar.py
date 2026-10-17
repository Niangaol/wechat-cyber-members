"""只读：找出主窗口左侧边栏各图标的真实 y 中心（灰阶/彩色团块）。"""
import sys
sys.path.insert(0, "/mnt/d/AgentPrograms/wechat-bot/src")
from PIL import Image
import numpy as np

img = Image.open("/mnt/d/AgentPrograms/wechat-bot/shots/root7.png").convert("RGB")
# 主窗口在 (0,0)-(1021,740)，侧边栏 x≈14..52
band = np.asarray(img.crop((14, 60, 52, 380)))
gray = band.mean(axis=2)
rows = (gray < 235).sum(axis=1)          # 每行"有内容"的像素数
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
for a, b in runs:
    print("icon band y=%d..%d center=%d" % (a, b, (a + b) // 2))
