"""重录「很帅的年糕」的列表锚点 + 标题模板（OCR 把它读成"很诈的年粒"，只能靠像素认）。"""
import json, sys, time
from pathlib import Path
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from wechat_ui import WeChatUI                                 # noqa: E402
import chat_anchors                                            # noqa: E402
from chat_navigator import find_chat_in_list, ChatNavigator    # noqa: E402

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
name = "很帅的年糕"
ui = WeChatUI(cfg)
img = ui.capture()

# 1) 列表锚点：从截图看到的行位置（第三行，y≈237）取标题文字区
row = img.crop((chat_anchors.LIST_X[0], 227, chat_anchors.LIST_X[1], 257))
path = chat_anchors.anchor_path(name, "list")
path.parent.mkdir(parents=True, exist_ok=True)
row.save(path)
print("列表锚点:", path.name, row.size, "| find_list_anchor ->", chat_anchors.find_list_anchor(name, img))

# 2) 点开它，确认标题栏，再把标题栏存成模板
pos = find_chat_in_list(ui, img, name) or chat_anchors.find_list_anchor(name, img)
print("定位 ->", pos)
ui.run(["xdotool", "mousemove", str(pos[0]), str(pos[1])])
ui.run(["xdotool", "click", "1"])
time.sleep(2)
after = ui.capture()
after.save(ROOT + "/shots/target-chat-open.png")
title = after.crop(chat_anchors.TITLE_BOX)
tpl = Path(ROOT) / "config" / "target-title.png"
tpl.write_bytes(title.convert("RGB").tobytes() and __import__("io").BytesIO(
    (lambda b: (title.convert("RGB").save(b, "PNG"), b)[1])(__import__("io").BytesIO())).getvalue())
print("标题模板已更新:", tpl)
print("标题 OCR:", repr(ui.ocr(after.crop((283, 20, 700, 61)), 7)))
print("title_anchor_matches ->", chat_anchors.title_anchor_matches(name, after))
