import json, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, "/mnt/d/AgentPrograms/wechat-bot/src")
from wechat_ui import WeChatUI
from moments_publisher import MomentsPublisher
from moment_release import load_coords

cfg = json.loads(Path("/mnt/d/AgentPrograms/wechat-bot/config/resident.json").read_text())
ui = WeChatUI(cfg)
coords = load_coords(cfg)
coords["text_input"] = [285, 140]

def sh(args):
    return ui.run(args, timeout=20)

def shot_bytes():
    return pub._shot().tobytes()

pub = MomentsPublisher(ui, {"moments_icon": coords.get("moments_icon"),
                            "text_input": coords["text_input"]})
report = {}
sh(["xdotool", "windowraise", "14682371"])
time.sleep(0.5)
sh(["xdotool", "mousemove", "638", "254"])
time.sleep(0.2)
loc = sh(["xdotool", "getmouselocation"]).decode()
report["under_pointer_after_raise"] = loc.strip()
before = shot_bytes()
sh(["xdotool", "click", "1"])
time.sleep(0.5)
sh(["xdotool", "type", "--clearmodifiers", "ABC123"])
time.sleep(1.0)
after_type = shot_bytes()
report["xtest_type_changed"] = after_type != before
# xclip 文本剪贴板（守护进程持剪贴板，与 xsel 不同实现）
p = subprocess.Popen(["xclip", "-selection", "clipboard"],
                     stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, env=ui.env)
p.stdin.write("DEF456".encode()); p.stdin.close(); time.sleep(0.8)
sh(["xdotool", "key", "--clearmodifiers", "ctrl+v"])
time.sleep(1.2)
after_paste = shot_bytes()
report["xclip_paste_changed"] = after_paste != after_type
pub._shot().save("/tmp/probe-paste4.png")
print(json.dumps(report, ensure_ascii=False))
