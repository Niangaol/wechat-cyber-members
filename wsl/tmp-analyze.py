from PIL import Image
im = Image.open('/mnt/d/AgentPrograms/wechat-bot/wsl/cal-comment-typed.png').convert('RGB')
w, h = im.size
px = im.load()
# 绿色 Send 按钮（启用态）
greens = []
for y in range(400, h):
    for x in range(350, w):
        r, g, b = px[x, y]
        if abs(r-7) < 40 and abs(g-193) < 40 and abs(b-96) < 40:
            greens.append((x, y))
if greens:
    xs = [p[0] for p in greens]
    ys = [p[1] for p in greens]
    print('SEND green bbox:', min(xs), min(ys), max(xs), max(ys),
          'center', (min(xs)+max(xs))//2, (min(ys)+max(ys))//2, 'count', len(greens))
# 输入框绿边框范围
border = []
for y in range(400, h):
    for x in range(w):
        r, g, b = px[x, y]
        if g > 150 and r < 100 and b < 150 and g - r > 60:
            border.append((x, y))
if border:
    xs = [p[0] for p in border]
    ys = [p[1] for p in border]
    print('INPUT green-ish bbox:', min(xs), min(ys), max(xs), max(ys))
