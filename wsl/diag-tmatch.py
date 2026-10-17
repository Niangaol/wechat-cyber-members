import sys, json
from pathlib import Path
sys.path.insert(0, '/mnt/d/AgentPrograms/wechat-bot/src')
from wechat_ui import WeChatUI
import numpy as np
from PIL import Image, ImageOps

cfg = json.loads(Path('/mnt/d/AgentPrograms/wechat-bot/config/resident.json').read_text())
ui = WeChatUI(cfg)
img = ui.capture()
region = img.crop((60, 60, 340, 555))
r = np.asarray(ImageOps.grayscale(region), dtype='float32')
t = np.asarray(ImageOps.grayscale(Image.open('/mnt/d/AgentPrograms/wechat-bot/config/chat-template.png')), dtype='float32')
th, tw = t.shape
t_n = t - t.mean(); t_den = float((t_n*t_n).sum()) or 1.0
scores = []
for y in range(0, r.shape[0]-th+1, 2):
    win = r[y:y+th, :tw]; w_n = win - win.mean()
    den = float((w_n*w_n).sum()) or 1.0
    scores.append((float((w_n*t_n).sum())/((den*t_den)**0.5), y))
scores.sort(reverse=True)
print('Top5 分数（区域y / 全屏y）:')
for s, y in scores[:5]:
    print('  %.3f  y=%d (全屏 %d)' % (s, y, y+60))
