"""只读实验：会话列表像素锚点在当前渲染下的匹配分数（粗体/未读会掉分）。"""
import sys, json
sys.path.insert(0, "/mnt/d/AgentPrograms/wechat-bot/src")
from pathlib import Path
import numpy as np
from PIL import Image
from wechat_ui import WeChatUI
from chat_anchors import anchor_path, text_mask, LIST_X

def dilate(m):
    d = m.copy()
    d[1:, :] |= m[:-1, :]
    d[:-1, :] |= m[1:, :]
    d[:, 1:] |= m[:, :-1]
    d[:, :-1] |= m[:, 1:]
    return d

cfg = json.loads(Path("/mnt/d/AgentPrograms/wechat-bot/config/resident.json").read_text())
ui = WeChatUI(cfg)
img = ui.capture()
region = np.asarray(text_mask(img.crop((LIST_X[0], 70, LIST_X[1], min(img.height, 555))))) < 140
for name in ["很帅的年糕", "Agent 聊天测试群"]:
    p = anchor_path(name, "list")
    with Image.open(p) as tpl:
        t = np.asarray(text_mask(tpl)) < 140
    h = t.shape[0]
    raw, dil = [], []
    for y in range(region.shape[0] - h + 1):
        win = region[y:y+h]
        raw.append(2 * np.logical_and(t, win).sum() / max(1, int(t.sum() + win.sum())))
        td, wd = dilate(t), dilate(win)
        dil.append(2 * np.logical_and(td, wd).sum() / max(1, int(td.sum() + wd.sum())))
    idx_raw = int(np.argmax(raw)); idx_dil = int(np.argmax(dil))
    print("==", name, "template", t.shape)
    print("   raw  best %.3f at y=%d  (2nd %.3f)" % (raw[idx_raw], 70+idx_raw+h//2, sorted(raw)[-2]))
    print("   dil  best %.3f at y=%d  (2nd %.3f)" % (dil[idx_dil], 70+idx_dil+h//2, sorted(dil)[-2]))
    print("   raw>0.95:", sum(1 for s in raw if s >= 0.95), " dil>0.90:", sum(1 for s in dil if s >= 0.90), " dil>0.85:", sum(1 for s in dil if s >= 0.85))
