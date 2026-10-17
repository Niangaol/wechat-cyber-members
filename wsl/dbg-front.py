"""诊断：朋友圈窗口是否真的在最上层（打印整屏与窗口同位置的平均差异）。"""
import sys, json, time, io
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from pathlib import Path
import numpy as np
from PIL import Image
from wechat_ui import WeChatUI
from moment_release import load_coords
from moments_publisher import MomentsPublisher

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
pub = MomentsPublisher(ui, load_coords(cfg))
wid = pub.find_moments_window()
print("wid:", wid)
if not wid:
    raise SystemExit(0)
pub.raise_moments(wid)
x, y = pub._win_origin(wid)
print("origin:", (x, y))
shot = pub._shot()
root = Image.open(io.BytesIO(pub._sh(["import", "-window", "root", "png:-"], timeout=40))).convert("RGB")
print("shot:", shot.size, "root:", root.size)
box = (max(0, x), max(0, y), min(root.width, x + shot.width), min(root.height, y + shot.height))
crop = root.crop(box)
a = np.asarray(crop.convert("L"), dtype="int16")
b = np.asarray(shot.convert("L").crop((0, 0, a.shape[1], a.shape[0])), dtype="int16")
print("box:", box, "crop:", crop.size, "MAD:", round(float(abs(a - b).mean()), 2))
shot.save(ROOT + "/shots/front-window.png")
crop.save(ROOT + "/shots/front-root-crop.png")
