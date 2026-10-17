import json, sys, time
from pathlib import Path
sys.path.insert(0, "/mnt/d/AgentPrograms/wechat-bot/src")
from wechat_ui import WeChatUI
from moments_publisher import MomentsPublisher
from moment_release import load_coords

cfg = json.loads(Path("/mnt/d/AgentPrograms/wechat-bot/config/resident.json").read_text())
ui = WeChatUI(cfg)
coords = load_coords(cfg)
coords["text_input"] = [285, 140]
# MomentsPublisher._click 需要 _win_origin，能在假/真窗口下工作
pub = MomentsPublisher(ui, {"moments_icon": coords.get("moments_icon"),
                            "text_input": coords["text_input"]})
try:
    pub._click("text_input")
except Exception as e:
    print("click path:", type(e).__name__, str(e)[:80])
ui.clipboard_write("TEST123")
ui.run(["xdotool", "windowfocus", pub.moments_wid])
ui.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"])
time.sleep(1.0)
shot = pub._shot()
shot.save("/tmp/probe-paste1.png")
# 兜底：--window 直送 type（Qt 对话框当年就是这样键入成功的）
ui.run(["xdotool", "type", "--window", pub.moments_wid, "--clearmodifiers", "FALLBACK456"])
time.sleep(1.0)
shot2 = pub._shot()
shot2.save("/tmp/probe-paste2.png")
import hashlib
print(json.dumps({"same": shot.tobytes() == shot2.tobytes()}, ensure_ascii=False))
