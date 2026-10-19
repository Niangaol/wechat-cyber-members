import io, os, subprocess, sys
env = dict(os.environ, DISPLAY=":99")
def run(a, t=20):
    return subprocess.run(a, capture_output=True, env=env, timeout=t, check=True).stdout
from PIL import Image
wid = run(["xdotool", "search", "--name", "Weixin"]).decode().split()[0]
im = Image.open(io.BytesIO(run(["import", "-window", wid, "png:-"]))).convert("RGB")
im.save("wsl/_shot.png")
im.crop((283, 20, 900, 61)).resize((1234, 82)).save("wsl/_title.png")
t = run(["tesseract", "wsl/_title.png", "stdout", "-l", "chi_sim", "--psm", "7"], 30).decode().strip()
print("当前窗口标题:", t)
im.crop((0, 88, 300, 200)).resize((600, 224)).save("wsl/_rows.png")
r = run(["tesseract", "wsl/_rows.png", "stdout", "-l", "chi_sim+eng", "--psm", "6"], 30).decode().strip()
print("列表前两行:", r.replace(chr(10), " | "))
