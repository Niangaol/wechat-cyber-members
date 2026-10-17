import json, sys, time, subprocess
from pathlib import Path
sys.path.insert(0, "/mnt/d/AgentPrograms/wechat-bot/src")
from wechat_ui import WeChatUI
from moments_publisher import MomentsPublisher
from moment_release import load_coords

cfg = json.loads(Path("/mnt/d/AgentPrograms/wechat-bot/config/resident.json").read_text())
ui = WeChatUI(cfg)
coords = load_coords(cfg)
coords["text_input"] = [285, 140]
pub = MomentsPublisher(ui, {"moments_icon": coords.get("moments_icon"),
                            "text_input": coords["text_input"]})
report = {}
wid = pub.open_moments_panel()
report["wid"] = wid
pub._sh(["xdotool", "windowraise", wid])
time.sleep(0.4)
before = pub._shot()
pub._click("text_input")
sh = lambda a: ui.run(a, timeout=20)
sh(["xdotool", "type", "--clearmodifiers", "ABC123"])
time.sleep(1.0)
after_type = pub._shot()
report["xtest_type_changed"] = after_type.tobytes() != before.tobytes()
p = subprocess.Popen(["xclip", "-selection", "clipboard"],
                     stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, env=ui.env)
p.stdin.write("DEF456".encode()); p.stdin.close(); time.sleep(0.8)
sh(["xdotool", "key", "--clearmodifiers", "ctrl+v"])
time.sleep(1.2)
after_paste = pub._shot()
report["xclip_paste_changed"] = after_paste.tobytes() != after_type.tobytes()
after_paste.save("/tmp/probe5.png")
print(json.dumps(report, ensure_ascii=False))
