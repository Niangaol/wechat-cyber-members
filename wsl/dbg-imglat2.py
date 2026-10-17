"""确认上限 2 张时的真实耗时（真模型调用一次）。"""
import sys, json, os, glob, time
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from pathlib import Path
from multimodal import StepPlan
cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
media = sorted(glob.glob(os.path.expanduser("~/.local/state/wechat-bot/media/inbox/**/*.png"), recursive=True),
               key=os.path.getmtime)
tl = [{"direction": "in", "kind": "image", "text": "", "image_path": p} for p in media[-2:]]
tl.append({"direction": "in", "kind": "text", "text": "这是什么", "image_path": ""})
sp = StepPlan(cfg)
t0 = time.time()
r = sp.reply([{"direction": "in", "kind": "text", "text": "这是什么"}], [], [],
             chat_context={"style": "", "facts": [], "timeline": tl})
print("limit=%s images=2 took=%.1fs reply=%s" % (cfg.get("reply_image_limit"), time.time() - t0, r[:70]))
