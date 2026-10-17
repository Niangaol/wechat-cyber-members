"""朋友圈编辑页控件标定：找文字输入框和 Post 按钮的绝对坐标。

用法: python3 wsl/calibrate-compose.py
"""
import io
import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ENV = dict(os.environ)
try:
    ENV['DISPLAY'] = json.loads((ROOT / 'config' / 'resident.json').read_text())['display']
except Exception:
    ENV.setdefault('DISPLAY', ':99')

WECHAT_GREEN = (8, 195, 99)


def sh(args, timeout=20):
    return subprocess.run(args, capture_output=True, timeout=timeout,
                          env=ENV).stdout.decode('utf-8', 'ignore')


def find_moments():
    ids = [t for t in sh(['xdotool', 'search', '--name', '^Moments$']).split() if t.isdigit()]
    return ids[0] if ids else None


def main():
    wid = find_moments()
    if not wid:
        print(json.dumps({'event': 'no_moments_window'}, ensure_ascii=False))
        return 2
    info = sh(['xdotool', 'getwindowgeometry', wid])
    pos = [l for l in info.splitlines() if 'Position' in l][0]
    wx, wy = (int(v) for v in pos.split(':')[1].split('(')[0].strip().split(','))
    raw = subprocess.run(['import', '-window', wid, 'png:-'],
                         capture_output=True, timeout=30, env=ENV).stdout
    im = Image.open(io.BytesIO(raw)).convert('RGB')
    w, h = im.size
    px = im.load()

    # 1) 绿色 Post 按钮：微信绿的大块区域
    green = []
    for y in range(0, h):
        for x in range(0, w):
            r, g, b = px[x, y]
            if abs(r - WECHAT_GREEN[0]) <= 40 and abs(g - WECHAT_GREEN[1]) <= 40 \
                    and abs(b - WECHAT_GREEN[2]) <= 40:
                green.append((x, y))
    post = None
    if green:
        xs = [p[0] for p in green]
        ys = [p[1] for p in green]
        post = {'cx': (min(xs) + max(xs)) // 2, 'cy': (min(ys) + max(ys)) // 2,
                'box': [min(xs), min(ys), max(xs), max(ys)], 'px': len(green)}

    # 2) 文字输入区：编辑卡片顶部的大片白色区域（在绿色按钮上方）
    text_area = None
    if post:
        ytop = post['box'][1]
        # 从卡片顶部往下找第一段连续的白色行带（Say something 那一行）
        rows = []
        for y in range(10, min(ytop - 10, h)):
            xs = [x for x in range(40, w - 40) if px[x, y] == (255, 255, 255)]
            if len(xs) > (w - 80) * 0.5:
                rows.append((y, min(xs), max(xs)))
        if rows:
            y0 = rows[0][0]
            y1 = rows[-1][0]
            x0 = min(r[1] for r in rows)
            x1 = max(r[2] for r in rows)
            text_area = {'cx': (x0 + x1) // 2, 'cy': (y0 + y1) // 2,
                         'box': [x0, y0, x1, y1]}

    ann = im.copy()
    d = ImageDraw.Draw(ann)
    if text_area:
        d.rectangle(text_area['box'], outline=(255, 0, 0), width=2)
        d.text((text_area['box'][0], text_area['box'][1] - 12), 'text_input', fill=(255, 0, 0))
    if post:
        d.rectangle(post['box'], outline=(0, 0, 255), width=2)
        d.text((post['box'][0], post['box'][1] - 12), 'post_button', fill=(0, 0, 255))
    ann_path = '/mnt/d/AgentPrograms/wechat-bot/wsl/compose-annotated.png'
    ann.save(ann_path)
    print(json.dumps({
        'event': 'compose_calibrated',
        'wid': wid, 'origin': [wx, wy], 'size': [w, h],
        'text_input': text_area,
        'post_button': post,
        'absolute': {
            'text_input': [wx + text_area['cx'], wy + text_area['cy']] if text_area else None,
            'publish_button': [wx + post['cx'], wy + post['cy']] if post else None,
        },
        'annotated': ann_path,
    }, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
