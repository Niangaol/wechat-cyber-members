"""侦察：聊天列表 OCR + 点开含 Deep 的那行读完整标题。"""
import sys, json, time
from pathlib import Path
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from wechat_ui import WeChatUI                        # noqa: E402
from chat_navigator import ocr_tsv, ChatNavigator     # noqa: E402

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
img = ui.capture()
print("列表 OCR（x<290 视为列表）:")
rows = {}
for text, x, y, w, h in ocr_tsv(ui, img):
    if x < 290 and text.strip():
        print("   x=%-4d y=%-4d %s" % (x, y, text.strip()))
        rows.setdefault(y, []).append(text.strip())

hit = None
for y, texts in sorted(rows.items()):
    if "deep" in " ".join(texts).lower():
        hit = (y, " ".join(texts)); break
print("命中行:", hit)
if hit:
    ui.run(["xdotool", "mousemove", "170", str(hit[0] + 5)])
    time.sleep(0.3)
    ui.run(["xdotool", "click", "1"])
    time.sleep(2)
    nav = ChatNavigator(ui)
    shot = ui.capture()
    shot.save(ROOT + "/shots/deepseek-open.png")
    print("current_title() ->", repr(nav.current_title(shot)))
