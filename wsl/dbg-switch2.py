"""测 switch_to 到新好友：先切回很帅的年糕，再切到 Deepseek，逐步打印。"""
import sys, json, time
from pathlib import Path
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from wechat_ui import WeChatUI                        # noqa: E402
from chat_navigator import ChatNavigator, find_chat_in_list   # noqa: E402

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
nav = ChatNavigator(ui)
img = ui.capture()
print("当前标题:", repr(nav.current_title(img)))

for name in ("很帅的年糕", "Deepseek"):
    img = ui.capture()
    print("--- 目标 %s" % name)
    print("   current:", repr(nav.current_title(img)),
          "| _matches_title:", nav._matches_title(img, name))
    pos = find_chat_in_list(ui, img, name)
    print("   find_chat_in_list ->", pos)
    try:
        out_img = nav.switch_to(name)
        print("   switch_to ✓ 新标题:", repr(nav.current_title(out_img)))
    except Exception as exc:                          # noqa: BLE001
        print("   switch_to ✗ %s: %s" % (type(exc).__name__, str(exc)[:120]))
    time.sleep(0.5)
