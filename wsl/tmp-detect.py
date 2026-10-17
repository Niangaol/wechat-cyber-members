from PIL import Image

def find_more_buttons(path):
    im = Image.open(path).convert('RGB')
    px = im.load()
    w, h = im.size
    hits = []
    y = 300
    while y < h - 12:
        band_bg = 0
        band_dot = 0
        for yy in range(y - 9, y + 10):
            for xx in range(515, 547):
                r, g, b = px[xx, yy]
                if (r, g, b) == (247, 247, 247):
                    band_bg += 1
                elif 60 < r < 140 and 80 < g < 150 and 120 < b < 190:
                    band_dot += 1
        if band_bg >= 250 and band_dot >= 4:
            hits.append((530, y, band_bg, band_dot))
            y += 30
        else:
            y += 2
    return hits

for p in ['/mnt/d/AgentPrograms/wechat-bot/wsl/cal-feed-scrolled2.png',
          '/mnt/d/AgentPrograms/wechat-bot/wsl/cal-comment-escaped.png']:
    print(p.split('/')[-1], find_more_buttons(p))
