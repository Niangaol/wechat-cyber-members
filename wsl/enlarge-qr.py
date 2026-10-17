from PIL import Image, ImageFilter
from pathlib import Path

src = Path('/mnt/d/AgentPrograms/wechat-bot/wechat-qr.png')
im = Image.open(src).convert('RGB')
w, h = im.size
print('原图:', w, 'x', h)

# 二维码区域：登录窗 292x396 里 QR 大致在中央 (45,45)-(250,250)，保守多留边
crop = im.crop((40, 40, min(255, w), min(260, h)))
# 4 倍放大 + 锐化，让手机摄像头能对上焦
big = crop.resize((crop.width * 4, crop.height * 4), Image.LANCZOS)
big = big.filter(ImageFilter.UnsharpMask(radius=2, percent=120, threshold=2))
out = Path('/mnt/d/AgentPrograms/wechat-bot/wechat-qr-big.png')
big.save(out)
print('放大图:', big.width, 'x', big.height, '->', out, out.stat().st_size, 'bytes')
