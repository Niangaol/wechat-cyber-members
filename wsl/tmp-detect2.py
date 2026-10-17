from PIL import Image

def find_more_buttons(path):
    im = Image.open(path).convert('RGB')
    px = im.load()
    w, h = im.size
    rows = []
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
            rows.append(y)
        y += 1
    # 聚簇取中点
    clusters = []
    for y in rows:
        if clusters and y - clusters[-1][-1] <= 3:
            clusters[-1].append(y)
        else:
            clusters.append([y])
    return [(530, sum(c) // len(c), len(c)) for c in clusters]

for p in ['cal-feed-scrolled2.png', 'cal-comment-escaped.png', 'cal-after-save.png']:
    print(p, find_more_buttons('/mnt/d/AgentPrograms/wechat-bot/wsl/' + p))
