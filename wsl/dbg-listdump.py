"""看看列表 OCR 到底读出了什么（全量打印），并截图存下来对照。"""
import json, sys
from pathlib import Path
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from wechat_ui import WeChatUI                                 # noqa: E402
from chat_navigator import ocr_tsv, merge_list_lines           # noqa: E402

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
img = ui.capture()
img.save(ROOT + "/shots/list-now.png")
print("窗口:", img.size)
words = ocr_tsv(ui, img.crop((60, 60, 283, 620)))
print("OCR 词块数:", len(words))
for cy, text, cx in merge_list_lines(words):
    print("  y=%-4d cx=%-4d %r" % (60 + cy, cx, str(text)[:40]))
