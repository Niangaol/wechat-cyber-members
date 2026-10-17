"""侦察：点开"人机"群，看看标题栏到底 OCR 成什么（为什么精确匹配失败）。"""
import json, sys, time
from pathlib import Path
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from wechat_ui import WeChatUI, title_matches                 # noqa: E402
from chat_navigator import ChatNavigator, find_chat_in_list, ocr_tsv, merge_list_lines  # noqa: E402

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
img = ui.capture()
pos = find_chat_in_list(ui, img, "人机")
print("find_chat_in_list ->", pos)
if pos:
    ax, ay = getattr(ui, "last_abs", (0, 0))
    ui.run(["xdotool", "mousemove", str(ax + pos[0]), str(ay + pos[1])])
    ui.run(["xdotool", "click", "1"])
    time.sleep(2)
    after = ui.capture()
    after.save(ROOT + "/shots/renji-open.png")
    raw = ui.ocr(after.crop((283, 20, 700, 61)), 7)
    print("标题栏 OCR 原文 =", repr(raw))
    nav = ChatNavigator(ui)
    print("current_title() =", repr(nav.current_title(after)))
    print("title_matches(is_group=True) ->", title_matches("人机", raw, True))
    print("title_matches(is_group=False) ->", title_matches("人机", raw, False))
    print("窗口尺寸:", after.size)
