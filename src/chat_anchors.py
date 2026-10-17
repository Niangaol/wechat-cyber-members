"""Name-bound, manually verified pixel anchors; never authorize policy by themselves."""
import hashlib
from pathlib import Path
from PIL import Image
ROOT = Path(__file__).resolve().parent.parent / 'config' / 'chat-anchors'
TITLE_BOX = (283, 20, 700, 61)
LIST_X = (120, 185)

def anchor_path(name, kind):
    key = ''.join(str(name).split())
    digest = hashlib.sha256(key.encode('utf-8')).hexdigest()
    return ROOT / (digest + '.' + kind + '.png')

def title_anchor_matches(name, image):
    if not name: return False
    path = anchor_path(name, 'title')
    if not path.exists(): return False
    with Image.open(path) as template:
        crop = image.crop(TITLE_BOX).convert('RGB')
        return template.size == crop.size and template.convert('RGB').tobytes() == crop.tobytes()

def text_mask(image):
    return image.convert('L').point(lambda p: 0 if p < 140 else 255)

ANCHOR_FLOOR = 0.60    # 最高分下限（粗体/未读渲染实测把 0.96 的同名锚点压到 0.69）
ANCHOR_MARGIN = 0.12   # 最高分必须比次高分高这么多，位置才算唯一


def find_list_anchor(name, image):
    """像素锚点定位会话行（只用于候选定位；授权仍靠点击后的完整标题核验）。

    Dice 阈值不能写死：同一条会话在未读/选中态会被渲染成粗体，实测同一个
    锚点分数从 0.96 掉到 0.69（2026-10-16 实录），写死 0.95 就永远点不动
    带未读红点的私聊——而那正是最需要回复的时候。改成"最高分够高且明显
    高于次高分"，位置仍然唯一，误定位由 _matches_title 兜底否决。
    """
    path = anchor_path(name, 'list')
    if not path.exists(): return None
    with Image.open(path) as template:
        template = text_mask(template)
        w, h = template.size
        if w != LIST_X[1] - LIST_X[0] or h > 40: return None
        if min(template.getdata()) == 255: return None
        region = text_mask(image.crop((LIST_X[0], 70, LIST_X[1], min(image.height, 555))))
        import numpy as np
        t = np.asarray(template) < 140
        r = np.asarray(region) < 140
        if r.shape[0] < h or r.shape[1] < w:
            return None
        scores = []
        for y in range(r.shape[0] - h + 1):
            win = r[y:y+h]
            scores.append(2 * np.logical_and(t, win).sum() / max(1, int(t.sum() + win.sum())))
        best_y = int(max(range(len(scores)), key=lambda i: scores[i]))
        best = scores[best_y]
        # 相邻 ±2 像素的窗口分数天然接近，比较次高分时要跳过
        others = [s for i, s in enumerate(scores) if abs(i - best_y) > 2]
        second = max(others) if others else 0.0
        if best >= ANCHOR_FLOOR and best - second >= ANCHOR_MARGIN:
            return (160, 70 + best_y + h // 2)
        return None
