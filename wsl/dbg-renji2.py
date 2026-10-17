"""为什么「人机」群 visible=0：切进去看画面 + 提取结果。"""
import json, sys
from pathlib import Path
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from wechat_ui import WeChatUI                                 # noqa: E402
from chat_navigator import ChatNavigator                       # noqa: E402
import visual_parse                                           # noqa: E402

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
nav = ChatNavigator(ui)
img = nav.switch_to("人机")
img.save(ROOT + "/shots/renji-group.png")
print("切换后标题 OCR:", repr(ui.ocr(img.crop((283, 20, 700, 61)), 7)))
print("窗口:", img.size)
bubbles = visual_parse.extract_messages(ui, img)
print("提取到气泡数:", len(bubbles))
for b in bubbles[:12]:
    print("   ", b.get("direction"), b.get("kind"), repr(str(b.get("text"))[:40]), b.get("bbox"))
chat = ui.chat_image(img)
print("聊天区尺寸:", chat.size)
