
from PIL import Image
im = Image.open('/mnt/d/AgentPrograms/wechat-bot/wsl/cal-sns-menu.png').convert('RGB')
w,h = im.size
px = im.load()
# 找分隔线（竖直亮线）和文字区域
cols = {}
for x in range(w):
    s = sum(px[x,y][0] for y in range(h))/h
    cols[x] = s
# 打印每列平均亮度找分隔
line = [x for x,v in cols.items() if v > 100]
print('bright cols (separator/text):', line[:20], '...' if len(line)>20 else '')
# 图标颜色（白色画 icon）
whites = [(x,y) for y in range(h) for x in range(w) if sum(px[x,y])>600]
if whites:
    xs=[p[0] for p in whites]; ys=[p[1] for p in whites]
    print('white icon/text bbox:', min(xs),min(ys),max(xs),max(ys))
# 左半/右半的亮像素分布
lw = [(x,y) for x,y in whites if x < w//2]
rw = [(x,y) for x,y in whites if x >= w//2]
for name, pts in [('LEFT(Like)',lw),('RIGHT(Comment)',rw)]:
    if pts:
        xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
        print(name, 'bbox', min(xs),min(ys),max(xs),max(ys), 'center', (min(xs)+max(xs))//2, (min(ys)+max(ys))//2)
print('menu origin (589,650)')
