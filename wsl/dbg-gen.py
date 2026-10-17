"""实机验证：qwen-image-2.1-turbo 生图链路（含 OC 参考图）现在还通不通。"""
import sys, json, os, time
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from pathlib import Path
import imagegen

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
oc = Path(ROOT + "/config/assets/oc-reference.png")
print("oc exists:", oc.exists())
t0 = time.time()
try:
    path = imagegen.generate("一只坐着喝茶的像素风小年糕，暖色灯光，桌面有红糖罐",
                             ref_image=str(oc) if oc.exists() else None,
                             **{k: v for k, v in (cfg.get("image_generation") or {}).items()
                                if k in ("base", "model")})
    size = os.path.getsize(path) if path and os.path.exists(path) else 0
    print("GEN OK %.1fs size=%.1fMB path=%s" % (time.time() - t0, size / 1048576, path))
except Exception as exc:
    print("GEN FAILED %.1fs %s %s" % (time.time() - t0, type(exc).__name__, str(exc)[:200]))
