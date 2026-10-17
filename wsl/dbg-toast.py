"""诊断：朋友圈窗口里的失败红条能不能被 OCR / 像素识别到。"""
import sys, json, io
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
shot = pub._shot()
shot.save(ROOT + "/shots/toast-dbg.png")
try:
    text = ui.ocr(shot, 6)
    print("OCR:", repr(text[:300]))
except Exception as e:
    print("OCR FAILED:", e)
px = np.asarray(shot.convert("RGB"), dtype="int16")
red = (px[:, :, 0] > 150) & (px[:, :, 1] < 90) & (px[:, :, 2] < 90)
print("red px:", int(red.sum()))
rows = red.sum(axis=1)
bands, start = [], None
for y, c in enumerate(rows):
    if c >= 30 and start is None:
        start = y
    elif c < 30 and start is not None:
        if y - start >= 8:
            bands.append((start, y - 1))
        start = None
for a, b in bands:
    xs = np.nonzero(red[a:b + 1].any(axis=0))[0]
    print("red band y=%d..%d x=%d..%d" % (a, b, xs.min(), xs.max()))
