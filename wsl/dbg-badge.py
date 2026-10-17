"""只读：聊天列表里"未读红点"能不能被识别（顺便证实监控会话的红点被吃掉了）。"""
import sys, json
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from pathlib import Path
import numpy as np
from wechat_ui import WeChatUI

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
img = ui.capture()
img.save(ROOT + "/shots/list-badges.png")
a = np.asarray(img.convert("RGB"), dtype="int16")
r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
red = (r > 190) & (r - g > 60) & (r - b > 60)
# 列表区：x 70..283（头像在 ~78..112），逐行统计红点数
rows = []
for y in range(60, img.height - 200):
    n = int(red[y, 70:283].sum())
    if n > 8:
        rows.append((y, n))
# 合并相邻行
merged = []
for y, n in rows:
    if merged and y - merged[-1][1] <= 3:
        merged[-1] = (merged[-1][0], y, merged[-1][2] + n)
    else:
        merged.append((y, y, n))
print("list red bands (y1,y2,pixels):")
for y1, y2, n in merged:
    print("   y=%d..%d  px=%d" % (y1, y2, n))
print("total red px in list:", int(red[60:img.height - 200, 70:283].sum()))
