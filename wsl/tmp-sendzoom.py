from PIL import Image, ImageDraw
im = Image.open('/mnt/d/AgentPrograms/wechat-bot/wsl/cal-comment-typed.png').convert('RGB')
crop = im.crop((380, 460, 573, 545))
d = ImageDraw.Draw(crop)
x = 0
while x < 193:
    d.line([(x, 0), (x, 85)], fill=(255, 0, 0), width=1)
    d.text((x+1, 1), str(x+380), fill=(255, 0, 0))
    x += 10
y = 0
while y < 85:
    d.line([(0, y), (193, y)], fill=(255, 0, 0), width=1)
    d.text((1, y+1), str(y+460), fill=(255, 0, 0))
    y += 10
crop = crop.resize((772, 340), Image.LANCZOS)
crop.save('/mnt/d/AgentPrograms/wechat-bot/wsl/cal-send-zoom.png')
print('saved')
