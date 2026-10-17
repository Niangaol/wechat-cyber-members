"""登录后坐标标定：像素分析定位 Moments 窗口关键元素，生成 COORDS 配置。"""
import json
from pathlib import Path

WECHAT_GREEN = (8, 195, 99)   # 微信绿（发送/发表按钮）


def _clusters(points, gap=8):
    """把点聚成团（按 x 再 y），返回每个团的包围盒。"""
    if not points:
        return []
    points = sorted(points)
    groups = [[points[0]]]
    for p in points[1:]:
        if p[0] - groups[-1][-1][0] <= gap:
            groups[-1].append(p)
        else:
            groups.append([p])
    boxes = []
    for g in groups:
        xs = [p[0] for p in g]; ys = [p[1] for p in g]
        boxes.append((min(xs), min(ys), max(xs), max(ys)))
    return boxes


def find_color_region(image, target, tolerance=40, min_pixels=30):
    """找指定颜色的区域（用于微信绿按钮）。返回 [(cx, cy, box), ...] 按像素数降序。"""
    w, h = image.size
    hits = {}
    px = image.load()
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            r, g, b = px[x, y][:3]
            if (abs(r - target[0]) <= tolerance and abs(g - target[1]) <= tolerance
                    and abs(b - target[2]) <= tolerance):
                hits.setdefault((x // 10, y // 10), []).append((x, y))
    regions = []
    for cell, pts in hits.items():
        if len(pts) >= min_pixels // 4:
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            box = (min(xs), min(ys), max(xs), max(ys))
            regions.append(((min(xs) + max(xs)) // 2, (min(ys) + max(ys)) // 2, box, len(pts)))
    regions.sort(key=lambda r: -r[3])
    return regions


def find_dark_icon(image, region, min_dark=20):
    """在指定区域内找深色图标团（用于左上角相机图标）。"""
    x1, y1, x2, y2 = region
    px = image.load()
    dark = []
    for y in range(max(0, y1), min(image.height, y2)):
        for x in range(max(0, x1), min(image.width, x2)):
            r, g, b = px[x, y][:3]
            if r < 100 and g < 100 and b < 100:
                dark.append((x, y))
    boxes = _clusters(dark)
    boxes = [b for b in boxes if (b[2]-b[0]) > 8 and (b[3]-b[1]) > 8]
    if not boxes:
        return None
    xs = sum((b[0]+b[2])//2 for b in boxes) // len(boxes)
    ys = sum((b[1]+b[3])//2 for b in boxes) // len(boxes)
    return (xs, ys)


def build_coords(image, moments_window_box):
    """从 Moments 窗口截图生成候选坐标（登录后人工确认）。"""
    ox, oy = moments_window_box[0], moments_window_box[1]
    coords = {}
    greens = find_color_region(image, WECHAT_GREEN)
    if greens:
        cx, cy = greens[0][0], greens[0][1]
        coords['publish_button'] = [ox + cx, oy + cy]
    # 左上角 80x80 区域找相机图标
    icon = find_dark_icon(image, (0, 0, min(80, image.width), min(80, image.height)))
    if icon:
        coords['camera_icon'] = [ox + icon[0], oy + icon[1]]
    return coords


def save_coords(coords, path=None):
    path = path or (Path(__file__).resolve().parent.parent / 'config' / 'moments-coords.json')
    path.write_text(json.dumps(coords, indent=2))
    return str(path)
