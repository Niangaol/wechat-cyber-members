"""为首条朋友圈（自我介绍）准备配图 + 文案文件（只准备，不发布）。"""
import sys, os, json
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from pathlib import Path
from PIL import Image
import imagegen

OUT = Path(ROOT) / "outbox"
OUT.mkdir(exist_ok=True)
prompt = (imagegen.oc_prefix() +
          "。场景：小年糕探险家第一天正式上岗，背着蓝色小工具包站在温暖的木桌前，"
          "桌上摆着一罐红糖，朝镜头挥手打招呼，表情开心自信。"
          "像素艺术风格，暖色调，画面干净无文字，不要出现任何文字。")
ref = imagegen.OC_REF if Path(imagegen.OC_REF).exists() else None
path = imagegen.generate(prompt, ref_image=ref)
print("generated:", path, "%.1fMB" % (os.path.getsize(path) / 1048576))

img = Image.open(path).convert("RGB")
small = img.resize((1080, 1080), Image.LANCZOS)
jpg = OUT / "first-post-image.jpg"
small.save(jpg, "JPEG", quality=90)
png = OUT / "first-post-image.png"
small.save(png, "PNG", optimize=True)
print("saved:", jpg, "%.0fKB" % (os.path.getsize(jpg) / 1024))
print("saved:", png, "%.0fKB" % (os.path.getsize(png) / 1024))
