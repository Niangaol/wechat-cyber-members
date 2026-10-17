"""朋友圈链路坐标标定：登录后跑一次，把结果写进 config/moments-coords.json。

为什么要有这个脚本：moments_publisher 里所有坐标默认 None，未标定的动作直接抛
NotImplementedError——宁可不动，也不瞎点。这个脚本负责把"点哪里"测出来。

四种模式：
  --nav        引导模式：你在 noVNC 里用鼠标点一下左侧"朋友圈"图标，
               脚本记录你点击的绝对坐标（最可靠，不猜）
  --panel      朋友圈面板已打开：像素分析找右上角相机图标
  --publish    发表页已打开（可含配图预览）：找文字输入框 + 绿色"发表"按钮
  --show       只打印当前已标定坐标

每个模式都会存一张带红框标注的截图到 /tmp/calib-*.png，人工核对用。
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]

from PIL import Image, ImageDraw  # noqa: E402

COORDS_FILE = ROOT / 'config' / 'moments-coords.json'
WECHAT_GREEN = (8, 195, 99)


def sh(args, timeout=15):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def main_window():
    """返回 (wid, x, y, w, h)；找不到就退出。"""
    out = sh(['xdotool', 'search', '--name', '^Weixin$']).stdout.split()
    if not out:
        out = sh(['xdotool', 'search', '--name', 'Weixin']).stdout.split()
    if not out:
        print(json.dumps({'event': 'no_window', 'hint': '微信未登录或主窗不在'}, ensure_ascii=False))
        return None
    wid = out[0]
    info = sh(['xdotool', 'getwindowgeometry', wid]).stdout
    pos = [l for l in info.splitlines() if 'Position' in l][0]
    geo = [l for l in info.splitlines() if 'Geometry' in l][0]
    x, y = (int(v) for v in pos.split('(')[1].split(')')[0].split(','))
    w, h = (int(v) for v in geo.split(':')[1].strip().split('x'))
    sh(['xdotool', 'windowactivate', wid])
    time.sleep(0.8)
    return wid, x, y, w, h


def shot(wid, path):
    p = subprocess.run(['import', '-window', wid, 'png:' + str(path)],
                       capture_output=True, timeout=30)
    if p.returncode != 0:
        raise SystemExit('截图失败: ' + p.stderr.decode()[:200])
    return Image.open(path).convert('RGB')


def load():
    if COORDS_FILE.exists():
        try:
            return {k: v for k, v in json.loads(COORDS_FILE.read_text()).items() if v}
        except Exception:
            pass
    return {}


def save(coords):
    COORDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    COORDS_FILE.write_text(json.dumps(coords, indent=2, ensure_ascii=False))
    return str(COORDS_FILE)


def annotate(image, marks, path):
    """marks: {label: (x, y, box)}，在副本上画红框+标签。"""
    im = image.copy()
    d = ImageDraw.Draw(im)
    for label, (cx, cy, box) in marks.items():
        if box:
            d.rectangle(box, outline=(255, 0, 0), width=2)
        d.ellipse((cx - 6, cy - 6, cx + 6, cy + 6), outline=(255, 0, 0), width=2)
        d.text((max(0, box[0]) if box else cx + 8, max(0, box[1] - 14) if box else cy - 18),
               label, fill=(255, 0, 0))
    im.save(path)
    return str(path)


def biggest_white_rect(image, min_side=80):
    """找最大的近白矩形（发表页的文字输入框）。返回 (cx, cy, box) 或 None。"""
    w, h = image.size
    px = image.load()
    white = [[False] * w for _ in range(h)]
    for y in range(0, h, 2):
        row = white[y]
        for x in range(0, w, 2):
            r, g, b = px[x, y]
            if r >= 235 and g >= 235 and b >= 235:
                row[x] = True
    best = None
    # 直方图法：按行统计白色像素，找连续高密度行带
    rows = []
    for y in range(0, h, 2):
        cnt = sum(1 for x in range(0, w, 4) if white[y][x])
        rows.append((y, cnt))
    band, cur = [], []
    for y, cnt in rows:
        if cnt >= (w // 4) * 0.5:
            cur.append(y)
        else:
            if len(cur) > 20:
                band.append(cur)
            cur = []
    if len(cur) > 20:
        band.append(cur)
    if not band:
        return None
    ys = max(band, key=len)
    # 在该行带内找白色列的起止
    y0, y1 = ys[0], ys[-1]
    xs = [x for x in range(0, w, 2) if white[(y0 + y1) // 2][x]]
    if not xs:
        return None
    x0, x1 = min(xs), max(xs)
    if (x1 - x0) < min_side or (y1 - y0) < min_side:
        return None
    return ((x0 + x1) // 2, (y0 + y1) // 2, (x0, y0, x1, y1))


def find_green(image, tolerance=40):
    w, h = image.size
    px = image.load()
    hits = []
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            r, g, b = px[x, y]
            if (abs(r - WECHAT_GREEN[0]) <= tolerance and abs(g - WECHAT_GREEN[1]) <= tolerance
                    and abs(b - WECHAT_GREEN[2]) <= tolerance):
                hits.append((x, y))
    if not hits:
        return None
    xs = [p[0] for p in hits]
    ys = [p[1] for p in hits]
    return ((min(xs) + max(xs)) // 2, (min(ys) + max(ys)) // 2, (min(xs), min(ys), max(xs), max(ys)))


def find_dark_icon(image, region):
    x1, y1, x2, y2 = region
    px = image.load()
    dark = []
    for y in range(max(0, y1), min(image.height, y2)):
        for x in range(max(0, x1), min(image.width, x2)):
            r, g, b = px[x, y]
            if r < 110 and g < 110 and b < 110:
                dark.append((x, y))
    if len(dark) < 40:
        return None
    xs = [p[0] for p in dark]
    ys = [p[1] for p in dark]
    return ((min(xs) + max(xs)) // 2, (min(ys) + max(ys)) // 2, (min(xs), min(ys), max(xs), max(ys)))


def abs_pt(origin, pt):
    return [origin[0] + pt[0], origin[1] + pt[1]]


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--nav', action='store_true', help='引导模式：等你在 noVNC 点朋友圈图标')
    g.add_argument('--panel', action='store_true', help='朋友圈面板：找相机图标')
    g.add_argument('--publish', action='store_true', help='发表页：找输入框和发表按钮')
    g.add_argument('--show', action='store_true')
    ap.add_argument('--timeout', type=int, default=120)
    args = ap.parse_args()

    coords = load()
    if args.show:
        print(json.dumps({'event': 'coords', 'coords': coords, 'file': str(COORDS_FILE)},
                         ensure_ascii=False))
        return 0

    win = main_window()
    if not win:
        return 2
    wid, wx, wy, ww, wh = win
    origin = (wx, wy)
    print(json.dumps({'event': 'window', 'wid': wid, 'origin': origin, 'size': [ww, wh]},
                     ensure_ascii=False), flush=True)

    if args.nav:
        print(json.dumps({'event': 'waiting_click',
                          'hint': '请在 noVNC 里用鼠标点一下左侧边栏的"朋友圈"图标（%d 秒内）'
                                  % args.timeout}, ensure_ascii=False), flush=True)
        last = sh(['xdotool', 'getmouselocation']).stdout
        deadline = time.time() + args.timeout
        seen_move = False
        while time.time() < deadline:
            time.sleep(0.4)
            cur = sh(['xdotool', 'getmouselocation']).stdout
            if cur != last:
                seen_move = True
                last = cur
                continue
            if seen_move and 'x:' in cur:
                # 鼠标停下：认为这一次停点就是目标图标
                parts = dict(p.split(':') for p in cur.split() if ':' in p)
                cx, cy = int(parts['x']), int(parts['y'])
                coords['moments_icon'] = [cx, cy]
                save(coords)
                print(json.dumps({'event': 'nav_calibrated', 'moments_icon': [cx, cy],
                                  'file': save(coords)}, ensure_ascii=False), flush=True)
                return 0
        print(json.dumps({'event': 'nav_timeout'}, ensure_ascii=False))
        return 3

    image = shot(wid, '/tmp/calib-current.png')

    if args.panel:
        # 相机图标：朋友圈面板右上角（相对面板左上角 1/3 宽以内、顶部 120px 内找深色图标）
        icon = find_dark_icon(image, (int(ww * 0.55), 8, ww - 8, 140))
        if not icon:
            icon = find_dark_icon(image, (0, 0, ww, 140))
        if not icon:
            print(json.dumps({'event': 'panel_no_icon',
                              'hint': '没找到相机图标；确认朋友圈面板已打开，或改用人工标注'},
                             ensure_ascii=False))
            return 4
        coords['camera_icon'] = abs_pt(origin, (icon[0], icon[1]))
        shot_path = annotate(image, {'camera_icon': icon}, '/tmp/calib-panel.png')
        print(json.dumps({'event': 'panel_calibrated', 'camera_icon': coords['camera_icon'],
                          'annotated': shot_path, 'file': save(coords)}, ensure_ascii=False))
        return 0

    if args.publish:
        marks = {}
        box = biggest_white_rect(image)
        if box:
            coords['text_input'] = abs_pt(origin, (box[0], box[1]))
            marks['text_input'] = box
        green = find_green(image)
        if green:
            coords['publish_button'] = abs_pt(origin, (green[0], green[1]))
            marks['publish_button'] = green
        if not marks:
            print(json.dumps({'event': 'publish_nothing_found',
                              'hint': '确认已打开发表页（有输入框和绿色发表按钮）'},
                             ensure_ascii=False))
            return 5
        shot_path = annotate(image, marks, '/tmp/calib-publish.png')
        print(json.dumps({'event': 'publish_calibrated',
                          'text_input': coords.get('text_input'),
                          'publish_button': coords.get('publish_button'),
                          'annotated': shot_path, 'file': save(coords)}, ensure_ascii=False))
        return 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
