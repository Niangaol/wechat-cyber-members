"""把当前会话的标题栏存成 target-title.png（只做这一步，避免上一次的写法错误）。"""
import json, sys, time
from pathlib import Path
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from wechat_ui import WeChatUI                                 # noqa: E402
import chat_anchors                                            # noqa: E402
from chat_navigator import find_chat_in_list                   # noqa: E402

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
name = "很帅的年糕"
ui = WeChatUI(cfg)
img = ui.capture()
pos = find_chat_in_list(ui, img, name)
print("定位 ->", pos)
if pos:
    ui.run(["xdotool", "mousemove", str(pos[0]), str(pos[1])])
    ui.run(["xdotool", "click", "1"])
    time.sleep(2)
img = ui.capture()
header = img.crop(chat_anchors.TITLE_BOX).convert("RGB")
tpl = Path(ROOT) / "config" / "target-title.png"
header.save(tpl)
print("标题模板:", tpl, header.size)
print("标题 OCR:", repr(ui.ocr(header, 7)))
print("title_anchor_matches ->", chat_anchors.title_anchor_matches(name, img))
