"""Moments 独立窗口图标标定：找顶部栏相机图标等关键坐标。

用法: python3 wsl/calibrate-moments-window.py
输出 JSON：图标团的窗口内坐标 + 绝对坐标 + 标注截图。
"""
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]

ENV = dict(os.environ)
try:
    ENV['DISPLAY'] = json.loads((ROOT / 'config' / 'resident.json').read_text())['display']
except Exception:
    ENV.setdefault('DISPLAY', ':99')


def sh(args, timeout=20):
    p = subprocess.run(args, capture_output=True, timeout=timeout, env=ENV)
    return p.stdout.decode('utf-8', 'ignore')


def find_moments():
    # xdotool search 返回十进制窗口 id（如 14680150），不是 0x 形式
    ids = [t for t in sh(['xdotool', 'search', '--name', '^Moments$']).split()
           if t.isdigit()]
    return ids[0] if ids else None


def capture(wid):
    raw = subprocess.run(['import', '-window', wid, 'png:-'],
                         capture_output=True, timeout=30, env=ENV).stdout
    return Image.open(io.BytesIO(raw)).convert('RGB')


def icon_clusters(image, y1, y2, x1=0, x2=None, min_px=25):
    """在指定行带内找图标团（与背景差异大的连通区域，按列投影）。"""
    x2 = x2 or image.width
    px = image.load()
    from collections import Counter
    bg = Counter(px[x, y] for y in range(y1, y2, 3)
                 for x in range(x1, x2, 4)).most_common(1)[0][0]
    cols = []
    for x in range(x1, x2):
        cnt = sum(1 for y in range(y1, y2)
                  if sum(abs(px[x, y][i] - bg[i]) for i in range(3)) > 60)
        cols.append((x, cnt))
    bands, cur = [], []
    for x, cnt in cols:
        if cnt >= 3:
            cur.append(x)
        else:
            if len(cur) >= 6:
                bands.append(cur)
            cur = []
    if len(cur) >= 6:
        bands.append(cur)
    out = []
    for band in bands:
        x0, x1c = band[0], band[-1]
        ys = [y for y in range(y1, y2) for x in band
              if sum(abs(px[x, y][i] - bg[i]) for i in range(3)) > 60]
        if not ys:
            continue
        y0, y1c = min(ys), max(ys)
        if (x1c - x0) * (y1c - y0) < min_px:
            continue
        out.append({'cx': (x0 + x1c) // 2, 'cy': (y0 + y1c) // 2,
                    'w': x1c - x0, 'h': y1c - y0,
                    'box': [x0, y0, x1c, y1c]})
    return out, bg


def main():
    wid = find_moments()
    if not wid:
        print(json.dumps({'event': 'no_moments_window',
                          'hint': '先点开朋友圈（主窗口左侧光圈图标）'}, ensure_ascii=False))
        return 2
    info = sh(['xdotool', 'getwindowgeometry', wid])
    pos = [l for l in info.splitlines() if 'Position' in l][0]
    wx, wy = (int(v) for v in pos.split(':')[1].split('(')[0].strip().split(','))
    im = capture(wid)
    # 顶部工具栏带（前 45 像素）
    clusters, bg = icon_clusters(im, 4, 48)
    ann = im.copy()
    d = ImageDraw.Draw(ann)
    for i, c in enumerate(clusters):
        d.rectangle(c['box'], outline=(255, 0, 0), width=2)
        d.text((c['box'][0], c['box'][3] + 2), str(i), fill=(255, 0, 0))
    ann_path = '/mnt/d/AgentPrograms/wechat-bot/wsl/moments-topbar-annotated.png'
    ann.crop((0, 0, min(200, im.width), 60)).save(ann_path)
    print(json.dumps({
        'event': 'moments_window',
        'wid': wid, 'origin': [wx, wy], 'size': list(im.size), 'bg': list(bg),
        'topbar_clusters': clusters,
        'absolute': [{'i': i, 'xy': [wx + c['cx'], wy + c['cy']]} for i, c in enumerate(clusters)],
        'annotated': ann_path,
        'note': '顶部栏顺序通常为 0通知铃铛 1相机 2刷新；相机是发布入口',
    }, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
