import sys
from PIL import Image
im = Image.open("/tmp/main-now.png")
sidebar = im.crop((10, 80, 60, 340)).resize((150, 780), Image.NEAREST)
sidebar.save("/tmp/sidebar-zoom.png")
old = Image.open("/tmp/wechat-current.png")
oldbar = old.crop((10, 80, 60, 340)).resize((150, 780), Image.NEAREST)
canvas = Image.new("RGB", (320, 780), (255, 255, 255))
canvas.paste(oldbar, (0, 0))
canvas.paste(sidebar, (165, 0))
canvas.save("/tmp/sidebar-compare.png")
print("left=earlier right=now")
