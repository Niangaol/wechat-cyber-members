"""只读：量朋友圈窗口顶栏图标（深色底上的浅色描边）的 x 位置。"""
import sys, json
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from pathlib import Path
import numpy as np
from PIL import Image
from wechat_ui import WeChatUI
from moment_release import load_coords
from moments_publisher import MomentsPublisher

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
pub = MomentsPublisher(WeChatUI(cfg), load_coords(cfg))
shot = pub._shot()
shot.save(ROOT + "/shots/topbar.png")
px = np.asarray(shot.convert("L"), dtype="int16")
print("shot", shot.size, "band mean", int(px[4:32, :].mean()))
band = px[4:34, :]
cols = (band > 120).sum(axis=0)
runs, start = [], None
for x, c in enumerate(cols):
    if c >= 2 and start is None:
        start = x
    elif c < 2 and start is not None:
        if x - start >= 4:
            runs.append((start, x - 1))
        start = None
print("light glyph x-ranges:", runs)
