"""诊断「人机」群为什么 visible=0：把提取链路每一段都打出来。"""
import json, sys
from pathlib import Path
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from wechat_ui import WeChatUI                                 # noqa: E402
from chat_navigator import ChatNavigator                       # noqa: E402
import visual_parse as vp                                      # noqa: E402

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
nav = ChatNavigator(ui)
img = nav.switch_to("人机")
img.save(ROOT + "/shots/renji-diag.png")
print("窗口:", img.size, "标题:", repr(ui.ocr(img.crop((283, 20, 700, 61)), 7)))

sidebar = 283 if img.width == 1021 else 273
bottom = img.height - 156
panels = vp._panels(img, sidebar + 64, bottom)
photos = vp._photo_panels(img, sidebar + 64, bottom)
print("白/绿气泡 panels:", len(panels), panels[:5])
print("图片气泡 photos:", len(photos), photos[:3])
for x in (sidebar + 22, img.width - 60):
    rows = vp.avatar_rows(img, x)
    print("头像行 x=%d -> %d 行" % (x, len(rows)), rows[:6])
bubbles = vp.extract_messages(img)
print("最终气泡:", len(bubbles))
for b in bubbles[:8]:
    print("   ", b.get('direction'), b.get('kind'), repr(str(b.get('text'))[:36]), b.get('bbox'))
