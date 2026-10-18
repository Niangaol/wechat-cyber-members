import sys, time
sys.path.insert(0, "src")
from pathlib import Path
from resident import Resident
from imagegen import generate, OC_REF
from wechat_ui import prepare_png_bytes
r = Resident.__new__(Resident)
topics = ["Qwen3.8-Flash 在 Qoder 限时免费，不扣 Credits", "群里问哪里能白嫖 API"]
for i, t in enumerate(topics, 1):
    p = r.image_prompt([{"text": t}])
    print("话题:", t)
    t0 = time.time()
    path = generate(p, ref_image=OC_REF)
    png, w, h = prepare_png_bytes(Path(path).read_bytes(), max_px=512)
    out = Path("wsl/_demo_%d.png" % i)
    out.write_bytes(png)
    print("  -> %s %dx%d %d bytes 用时 %.1fs" % (out.name, w, h, len(png), time.time() - t0))
