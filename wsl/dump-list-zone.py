from PIL import Image
im = Image.open('/mnt/d/AgentPrograms/wechat-bot/main-with-chat.png').convert('RGB')
print('主聊天截图尺寸:', im.size)
# 列表区域每 40px 一行 dump 暗像素数，找列表项边界
import numpy as np
a = np.asarray(im.convert('L'))
for y0 in range(60, 560, 20):
    row = a[y0:y0+20, 65:340]
    dark = int((row < 150).sum())
    print('y %3d-%3d 暗像素 %5d %s' % (y0, y0+20, dark, '#' * min(dark // 50, 30)))
