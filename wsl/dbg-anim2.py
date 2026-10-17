"""持锁只读：目标会话标题 + 两帧差异（排除另一个进程抢 UI 的干扰）。"""
import sys, json, time
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from pathlib import Path
import numpy as np
from wechat_ui import WeChatUI
from chat_navigator import ChatNavigator
from ui_lease import ui_lease

STATE = Path.home() / ".local" / "state" / "wechat-bot"
cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
nav = ChatNavigator(ui)
try:
    with ui_lease(STATE):
        img = nag = nav.switch_to("Agent 聊天测试群")
        print("title:", repr(nav.current_title(img)))
        crop = ui.chat_image(img)
        time.sleep(1.5)
        img2 = ui.capture()
        print("title2:", repr(nav.current_title(img2)))
        crop2 = ui.chat_image(img2)
        a = np.asarray(crop.convert("L"), dtype="int16")
        b = np.asarray(crop2.convert("L"), dtype="int16")
        diff = np.abs(a - b) > 24
        print("changed ratio %.4f count %d" % (diff.mean(), diff.sum()))
        ys, xs = np.nonzero(diff)
        if len(xs):
            print("bbox x=%d..%d y=%d..%d" % (xs.min(), xs.max(), ys.min(), ys.max()))
        crop2.save(ROOT + "/shots/busy-2.png")
except Exception as exc:
    print("FAILED", type(exc).__name__, str(exc)[:120])
