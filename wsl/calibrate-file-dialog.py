"""文件对话框控件标定：找 File name 输入框和 Open 按钮的绝对坐标。

用法: python3 wsl/calibrate-file-dialog.py
"""
import io
import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ENV = dict(os.environ)
try:
    ENV['DISPLAY'] = json.loads((ROOT / 'config' / 'resident.json').read_text())['display']
except Exception:
    ENV.setdefault('DISPLAY', ':99')


def sh(args, timeout=20):
    return subprocess.run(args, capture_output=True, timeout=timeout,
                          env=ENV).stdout.decode('utf-8', 'ignore')


def main():
    ids = [t for t in sh(['xdotool', 'search', '--name', '^Open$']).split() if t.isdigit()]
    if not ids:
        print(json.dumps({'event': 'no_dialog', 'hint': '先点朋友圈相机图标弹出文件框'},
                         ensure_ascii=False))
        return 2
    wid = ids[0]
    info = sh(['xdotool', 'getwindowgeometry', wid])
    pos = [l for l in info.splitlines() if 'Position' in l][0]
    wx, wy = (int(v) for v in pos.split(':')[1].split('(')[0].strip().split(','))
    raw = subprocess.run(['import', '-window', wid, 'png:-'],
                         capture_output=True, timeout=30, env=ENV).stdout
    im = Image.open(io.BytesIO(raw)).convert('RGB')
    w, h = im.size
    px = im.load()
    # 1) File name 输入框：把连续白色行分组，取"最下方的细长白带"
    #    （文件列表也是白底，但它是高带；输入框是 15-35px 高的细带）
    rows = []
    for y in range(int(h * 0.5), h):
        xs = [x for x in range(20, w - 20) if px[x, y] == (255, 255, 255)]
        if len(xs) > 150:
            rows.append((y, min(xs), max(xs)))
    bands, cur = [], []
    for r in rows:
        if cur and r[0] - cur[-1][0] > 2:
            bands.append(cur)
            cur = []
        cur.append(r)
    if cur:
        bands.append(cur)
    thin = [b for b in bands if 12 <= (b[-1][0] - b[0][0]) <= 40]
    if not thin:
        print(json.dumps({'event': 'no_input_field',
                          'bands': [[b[0][0], b[-1][0]] for b in bands]}, ensure_ascii=False))
        return 3
    target = thin[-1]                      # 最下方的细白带 = File name 输入框
    y0, y1 = target[0][0], target[-1][0]
    x0 = min(r[1] for r in target)
    x1 = max(r[2] for r in target)
    field = {'cx': (x0 + x1) // 2, 'cy': (y0 + y1) // 2,
             'box': [x0, y0, x1, y1]}
    # 2) Open 按钮：输入框同一行带、输入框右边界以右的控件
    band = []
    for y in range(y0 - 2, y1 + 3):
        for x in range(x1 + 8, w - 4):
            r, g, b = px[x, y]
            if r < 210 and g < 210 and b < 210:
                band.append((x, y))
    btn = None
    if band:
        bx0 = min(p[0] for p in band)
        bx1 = max(p[0] for p in band)
        by0 = min(p[1] for p in band)
        by1 = max(p[1] for p in band)
        btn = {'cx': (bx0 + bx1) // 2, 'cy': (by0 + by1) // 2,
               'box': [bx0, by0, bx1, by1]}
    # 标注
    from PIL import ImageDraw
    ann = im.copy()
    d = ImageDraw.Draw(ann)
    d.rectangle(field['box'], outline=(255, 0, 0), width=2)
    d.text((field['box'][0], field['box'][1] - 12), 'file_path_input', fill=(255, 0, 0))
    if btn:
        d.rectangle(btn['box'], outline=(0, 0, 255), width=2)
        d.text((btn['box'][0], btn['box'][1] - 12), 'open_button', fill=(0, 0, 255))
    ann_path = '/mnt/d/AgentPrograms/wechat-bot/wsl/file-dialog-annotated.png'
    ann.save(ann_path)
    print(json.dumps({
        'event': 'dialog_calibrated',
        'wid': wid, 'origin': [wx, wy], 'size': [w, h],
        'file_path_input': field,
        'open_button': btn,
        'absolute': {
            'file_path_input': [wx + field['cx'], wy + field['cy']],
            'file_open_button': [wx + btn['cx'], wy + btn['cy']] if btn else None,
        },
        'annotated': ann_path,
    }, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
