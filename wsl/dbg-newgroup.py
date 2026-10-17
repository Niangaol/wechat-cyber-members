"""点开新群，读准它的真实名字（列表 OCR 只会给个大概）。"""
import json, sys, time
from pathlib import Path
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from wechat_ui import WeChatUI
from chat_navigator import ocr_tsv, merge_list_lines

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
img = ui.capture()
words = ocr_tsv(ui, img.crop((60, 60, 283, 620)))
target = None
for cy, text, cx in merge_list_lines(words):
    t = str(text)
    if "招新" in t or "Vibe" in t or "vibe" in t or "Lab" in t:
        target = 60 + cy
        print("候选行 y=%d %r" % (target, t))
if target is None:
    print("列表里没找到含招新的行")
    sys.exit(1)
ui.run(["xdotool", "mousemove", str(170), str(target)])
ui.run(["xdotool", "click", "1"])
time.sleep(2)
after = ui.capture()
after.save(ROOT + "/shots/newgroup.png")
print("标题栏 OCR:", repr(ui.ocr(after.crop((283, 20, 760, 61)), 7)))
print("窗口:", after.size)