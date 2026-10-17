"""测 LongCat 2.5 Preview Free 能不能读图（决定回复是否还挂图片）。"""
import base64, io, json, sys, time
from pathlib import Path
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from PIL import Image                                # noqa: E402
from model_api import ModelProvider                  # noqa: E402

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
block = dict(cfg["model"]); block["enabled"] = True
block["model"] = "longcat-2.5-preview-free"
block["reasoning_effort"] = "medium"
p = ModelProvider(block, "probe")

src = Path(ROOT) / "config" / "assets" / "oc-reference.png"
img = Image.open(src).convert("RGB"); img.thumbnail((384, 384))
buf = io.BytesIO(); img.save(buf, "PNG")
url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

t0 = time.time()
try:
    text = p.chat([{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": url}},
        {"type": "text", "text": "一句话描述这张图里有什么。"}]}], 600)[0]
    print("读图 ✅ %.1fs 描述=%r" % (time.time() - t0, text[:80]))
except Exception as exc:                             # noqa: BLE001
    print("读图 ❌ %.1fs %s: %s" % (time.time() - t0, type(exc).__name__, str(exc)[:160]))
