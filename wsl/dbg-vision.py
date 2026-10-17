"""实机验证：图片消息能不能被"看懂"（走真实回复链路，一次模型调用）。"""
import sys, json, os, glob
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from pathlib import Path
from multimodal import StepPlan

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
media = sorted(glob.glob(os.path.expanduser("~/.local/state/wechat-bot/media/inbox/**/*.png"), recursive=True))
print("media files:", len(media))
for m in media[-3:]:
    print("  ", os.path.basename(m), os.path.getsize(m))
if not media:
    raise SystemExit("没有落盘的图片")
pic = media[-1]
timeline = [
    {"direction": "in", "kind": "text", "text": "你主人的电脑还开着吗", "image_path": ""},
    {"direction": "in", "kind": "image", "text": "", "image_path": pic},
    {"direction": "in", "kind": "text", "text": "这是什么", "image_path": ""},
]
sp = StepPlan(cfg)
reply = sp.reply([{"direction": "in", "kind": "text", "text": "这是什么"}], [], [],
                 chat_context={"style": "", "facts": [], "timeline": timeline})
print("REPLY:", reply)
