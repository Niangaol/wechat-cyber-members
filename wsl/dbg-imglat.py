"""测：回复时挂几张时间线图片，对耗时影响多大（真模型调用）。"""
import sys, json, os, glob, time
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from pathlib import Path
from multimodal import StepPlan

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
media = sorted(glob.glob(os.path.expanduser("~/.local/state/wechat-bot/media/inbox/**/*.png"), recursive=True),
               key=os.path.getmtime)
print("media files:", len(media))
sp = StepPlan(cfg)

def run(n):
    tl = [{"direction": "in", "kind": "image", "text": "", "image_path": p} for p in media[-n:]]
    tl.append({"direction": "in", "kind": "text", "text": "这是什么", "image_path": ""})
    t0 = time.time()
    try:
        r = sp.reply([{"direction": "in", "kind": "text", "text": "这是什么"}], [], [],
                     chat_context={"style": "", "facts": [], "timeline": tl})
        print("images=%d took=%.1fs reply=%s" % (n, time.time() - t0, r[:60]))
    except Exception as e:
        print("images=%d FAILED %.1fs %s %s" % (n, time.time() - t0, type(e).__name__, str(e)[:80]))

run(1)
run(6)
