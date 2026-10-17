"""侧边栏图标定位：像素分析找主窗口左侧图标列的中心坐标（用于标定 moments_icon）。

用法: python3 wsl/find-sidebar-icons.py
输出 JSON：每个图标团的 (cx, cy, w, h, green?) + 一张带标注的侧边栏截图。
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]

# 和 wechat_ui 一致：显式带上 DISPLAY，否则子进程里的 xdotool 打不开显示
ENV = dict(os.environ)
try:
    ENV['DISPLAY'] = json.loads((ROOT / 'config' / 'resident.json').read_text())['display']
except Exception:
    ENV.setdefault('DISPLAY', ':99')


def main_window():
    out = subprocess.run(['xdotool', 'search', '--name', '^Weixin$'],
                         capture_output=True, text=True, timeout=15, env=ENV).stdout.split()
    if not out:
        out = subprocess.run(['xdotool', 'search', '--name', 'Weixin'],
                             capture_output=True, text=True, timeout=15,
                             env=ENV).stdout.split()
    if not out:
        print(json.dumps({'event': 'no_window', 'display': ENV.get('DISPLAY')},
                         ensure_ascii=False))
        return None
    wid = out[0]
    info = subprocess.run(['xdotool', 'getwindowgeometry', wid],
                          capture_output=True, text=True, timeout=15, env=ENV).stdout
    pos = [l for l in info.splitlines() if 'Position' in l][0]
    # 形如 "  Position: 113,31 (screen: 0)"：取括号前的坐标部分
    x, y = (int(v) for v in pos.split(':')[1].split('(')[0].strip().split(','))
    subprocess.run(['xdotool', 'windowactivate', wid], timeout=15, env=ENV)
    time.sleep(0.8)
    return wid, x, y


def find_icon_clusters(image, x1=8, x2=72, y1=60, y2=None, min_px=120):
    """在侧边栏条带内找图标团：与背景色差异足够大的连通区域（按行投影聚合）。"""
    w, h = image.size
    y2 = y2 or h
    px = image.load()
    # 背景采样：取条带内最常见颜色
    from collections import Counter
    bg = Counter(px[x, y] for y in range(y1, min(y2, h), 7)
                 for x in range(x1, x2, 5)).most_common(1)[0][0]
    rows = []
    for y in range(y1, min(y2, h)):
        cnt = 0
        for x in range(x1, x2):
            r, g, b = px[x, y][:3]
            if abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) > 60:
                cnt += 1
        rows.append((y, cnt))
    bands, cur = [], []
    for y, cnt in rows:
        if cnt >= 6:
            cur.append(y)
        else:
            if len(cur) >= 12:
                bands.append(cur)
            cur = []
    if len(cur) >= 12:
        bands.append(cur)
    clusters = []
    for band in bands:
        ys = band
        y0, y1c = ys[0], ys[-1]
        xs = [x for y in ys for x in range(x1, x2)
              if sum(abs(px[x, y][i] - bg[i]) for i in range(3)) > 60]
        if not xs:
            continue
        x0, x1c = min(xs), max(xs)
        if (x1c - x0) * (y1c - y0) < min_px:
            continue
        # 绿色判定（活跃的聊天图标是微信绿）
        green = 0
        for y in range(y0, y1c + 1):
            for x in range(x0, x1c + 1):
                r, g, b = px[x, y][:3]
                if g > 150 and g - r > 40 and g - b > 40:
                    green += 1
        clusters.append({'cx': (x0 + x1c) // 2, 'cy': (y0 + y1c) // 2,
                         'w': x1c - x0, 'h': y1c - y0,
                         'green_px': green,
                         'is_green': green > 30})
    return clusters, bg


def main():
    win = main_window()
    if not win:
        return 2
    wid, wx, wy = win
    png = '/tmp/main-sidebar.png'
    subprocess.run(['import', '-window', wid, 'png:' + png],
                   capture_output=True, timeout=30, env=ENV)
    im = Image.open(png).convert('RGB')
    clusters, bg = find_icon_clusters(im)
    # 标注：红框 + 序号
    ann = im.copy()
    d = ImageDraw.Draw(ann)
    strip = im.crop((0, 0, 80, im.height))
    for i, c in enumerate(clusters):
        d.rectangle((c['cx'] - c['w'] // 2 - 2, c['cy'] - c['h'] // 2 - 2,
                     c['cx'] + c['w'] // 2 + 2, c['cy'] + c['h'] // 2 + 2),
                    outline=(255, 0, 0), width=2)
        d.text((c['cx'] + c['w'] // 2 + 4, c['cy'] - 8), str(i), fill=(255, 0, 0))
    ann_path = '/mnt/d/AgentPrograms/wechat-bot/wsl/sidebar-annotated.png'
    ann.crop((0, 0, 90, im.height)).save(ann_path)
    print(json.dumps({
        'event': 'sidebar_icons',
        'window': {'wid': wid, 'origin': [wx, wy], 'size': list(im.size)},
        'bg': list(bg),
        'clusters': clusters,
        'absolute': [{'i': i, 'xy': [wx + c['cx'], wy + c['cy']],
                      'is_green': c['is_green']} for i, c in enumerate(clusters)],
        'annotated': ann_path,
        'note': '图标顺序通常为 0聊天 1通讯录 2收藏 3朋友圈 4小程序；绿色=当前所在面板',
    }, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
