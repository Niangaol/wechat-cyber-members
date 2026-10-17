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
ui.run(["xdotool", "windowraise", "14682371"])
time.sleep(0.5)
ui.run(["xdotool", "windowfocus", "14682371"])
time.sleep(0.3)
mx, my = ui.last_abs if getattr(ui, "last_abs", None) else (0, 0)
# MomentsPublisher._click 内部用 _win_origin，等价于 raise 后相对点击
pub = MomentsPublisher(ui, {"moments_icon": coords.get("moments_icon"),
                            "text_input": coords["text_input"]})
before = pub._shot()
pub._click("text_input")
ui.clipboard_write("TEST123")
ui.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"])
time.sleep(1.2)
after = pub._shot()
after.save("/tmp/probe-paste3.png")
print(json.dumps({"changed": after.tobytes() != before.tobytes()}, ensure_ascii=False))
