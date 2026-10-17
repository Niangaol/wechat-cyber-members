"""本地头像行定位：不让VLM虚构消息坐标。布局尺寸自适应，无法确认就拒绝。"""
import hashlib
import logging
from pathlib import Path
from PIL import Image,ImageChops

# 已验证布局基准（980x710 与 1021x740 同比例缩放关系）
BASE_W, BASE_H = 980, 710

def _layout(image):
    """返回当前尺寸相对基准的缩放参数与关键 x 坐标（右侧按宽度自适应）。"""
    w, h = image.size
    if not (900 <= w <= 1200 and 650 <= h <= 900):
        raise ValueError('未验证的窗口尺寸: %dx%d' % (w, h))
    sx = w / BASE_W
    return sx

def groups(values,gap=5):
    result=[]
    for y in values:
        if not result or y-result[-1][-1]>gap: result.append([y])
        else: result[-1].append(y)
    return [(g[0],g[-1]+1) for g in result if g[-1]-g[0]>=23]

def avatar_rows(image,x):
    rows=[]
    for y in range(78, image.height - 156):
        n=0
        for dx in range(30):
            r,g,b=image.getpixel((x+dx,y))
            if abs(r-237)+abs(g-237)+abs(b-237)>45: n+=1
        if n>=6: rows.append(y)
    return groups(rows)

def has_at_mention(image, bbox):
    """检测 in 气泡内是否有蓝色 @高亮文字（微信群聊@我的特征）。
    保守策略：检测不到返回 False（宁漏不误，绝不把普通消息当@处理）。"""
    x1, y1, x2, y2 = bbox
    if x2 - x1 < 10 or y2 - y1 < 10:
        return False
    region = image.crop((x1, y1, x2, y2))
    pixels = list(region.getdata())
    blue = 0
    for r, g, b in pixels:
        # 微信@高亮蓝：蓝通道显著高于红绿，且整体不是纯白/纯灰
        if b > 150 and b - r > 60 and b - g > 40:
            blue += 1
    return blue >= 6  # 至少一小簇蓝色像素才算
def mention_exact(text, aliases):
    """精确别名匹配（'@年糕Agent' 这种）。OCR 容错版见 mentions_me。"""
    t = ''.join(str(text or '').split())
    for alias in aliases:
        a = ''.join(str(alias or '').split())
        if a and ('@' + a) in t:
            return True
    return False


def mentions_me(text, aliases):
    """@到本机器人的文本判断：微信 Linux 端的 @ 是纯黑文字（无蓝色高亮），只能按别名匹配。

    别名可能被 OCR 认错（实测 '@年糕 Agent 在吗' 读成 '@@年糙 Agent 在吗'），所以
    再加一层容错：@ 后面紧跟的片段与别名足够像也算在叫我。这里只是把消息提到
    最高优先级，误判的代价只是"回得快一点"，不会绕过任何安全闸。
    """
    from difflib import SequenceMatcher
    t = ''.join(str(text or '').split())
    if mention_exact(t, aliases):
        return True
    for alias in aliases:
        a = ''.join(str(alias or '').split())
        if len(a) < 2:
            continue
        for i, ch in enumerate(t):
            if ch != '@':
                continue
            frag = t[i + 1:i + 1 + len(a)]
            if len(frag) < max(2, len(a) - 1):
                continue
            if SequenceMatcher(None, a, frag).ratio() >= 0.6:
                return True
    return False


def _cjk_count(text):
    """中文字符数：多变体择优的依据（中文聊天里读不出中文就是失败）。"""
    return sum(1 for ch in str(text or '') if '\u4e00' <= ch <= '\u9fff')


def _ink_pixels(image):
    """气泡里实际有多少笔墨像素（判断"有文字但没读出来"）。"""
    import numpy as np
    a = np.asarray(image.convert('L'))
    return int((a < 140).sum())


def _local_best(ui, image, bbox):
    """本地 tesseract 多变体择优：零额度、约 0.5 秒，但中文不稳。"""
    import io
    from PIL import ImageOps
    x1, y1, x2, y2 = bbox
    crop = image.crop((max(0, x1), max(0, y1), min(image.width, x2), min(image.height, y2)))
    gray = ImageOps.grayscale(crop)
    variants = [
        gray.resize((gray.width*4, gray.height*4)),
        gray.resize((gray.width*4, gray.height*4)).point(lambda p: 0 if p < 150 else 255),
        gray.resize((gray.width*6, gray.height*6)).point(lambda p: 0 if p < 200 else 255),
        crop.resize((crop.width*4, crop.height*4)),
    ]
    best, best_score = '', None
    for img in variants:
        out = io.BytesIO(); img.save(out, 'PNG')
        text = ui.run(['tesseract', 'stdin', 'stdout', '-l', 'chi_sim+eng', '--psm', '7'],
                      out.getvalue(), timeout=25).decode('utf-8', 'ignore').strip()
        score = (_cjk_count(text), len(text))
        if best_score is None or score > best_score:
            best, best_score = text, score
    return best


def needs_model_ocr(text, image, bbox, aliases=()):
    """本地结果是否不可靠到值得花一次模型调用。

    两种情形（都很少见，保证日常零成本）：
      1) 有 @ 但匹配不上别名——@ 决定群消息优先级，读错代价高
      2) 一个中文字都没读出来，但气泡里明明有笔墨——中文聊天里的明显失败
    """
    if mention_exact(text, aliases):
        return False
    if '@' in str(text or ''):
        return True      # @ 但没精确匹配上别名：值得花一次模型读准它
    x1, y1, x2, y2 = bbox
    crop = image.crop((max(0, x1), max(0, y1), min(image.width, x2), min(image.height, y2)))
    return _cjk_count(text) == 0 and _ink_pixels(crop) > 40


def ocr_bubbles(ui, image, bboxes, model=None, aliases=(), force=False):
    """整屏气泡 OCR：本地逐泡免费打底，任一不可靠时用一次批量模型调用读全部。

    批量比逐泡省额度（1 次 vs N 次），模型还能借上下文互相校正（如"谁"不会读成"进"）。
    force=True 时跳过 needs_model_ocr 启发式——调用方已经确定值得花这一次
    （例如观察管道确认有真新消息）。启发式判不出"读得很自信但其实错"的垃圾
    （含 CJK 的乱码会被当成可靠读数），所以有新消息时直接走模型更稳。
    """
    locals_ = [_local_best(ui, image, b) for b in bboxes]
    if model is None:
        return locals_
    if not force and not any(needs_model_ocr(t, image, b, aliases)
                             for t, b in zip(locals_, bboxes)):
        return locals_
    try:
        batch = model.ocr_bubbles_image(image, bboxes)
    except Exception as exc:                        # noqa: BLE001
        # 别静默退回：模型纠正失败时一定要留下痕迹，否则"读到错字"会一直被当成正常
        logging.warning('ocr_model_fallback error=%s: %s', type(exc).__name__, str(exc)[:140])
        return locals_
    return [str(batch.get(i, '') or '').strip() or locals_[i] for i in range(len(locals_))]


def ocr_bubble(ui, image, bbox, model=None, aliases=()):
    """气泡级 OCR：本地多变体择优，不可靠时用视觉模型兜底。

    model 需提供 ocr_bubble_image(image)->str；调用方负责额度与异常隔离。
    """
    text = _local_best(ui, image, bbox)
    if model is None or not needs_model_ocr(text, image, bbox, aliases):
        return text
    try:
        better = model.ocr_bubble_image(image.crop(tuple(bbox)))
    except Exception:
        return text
    return (better or '').strip() or text


def classify(bubble, text):
    """按气泡特征判定消息类型：有文字→text；无文字大气泡→image；小气泡→sticker。"""
    # Color-rich media stays media even when OCR sees labels inside the picture.
    import numpy as np
    a = np.asarray(bubble.convert('RGB'), dtype='int16')
    colorful = (a.max(axis=2)-a.min(axis=2) > 45).mean()
    green = ((a[:,:,1] > 180) & (a[:,:,1]-a[:,:,0] > 30) & (a[:,:,1]-a[:,:,2] > 30)).mean()
    if text and (colorful < 0.04 or green > 0.65):
        return 'text'
    w, h = bubble.size
    area = w * h
    if area > 9000:   # 图片消息气泡通常较大
        return 'image'
    return 'sticker'   # 表情/贴图小气泡


def _components(mask, left, top=72, min_w=20, min_h=16, min_px=250):
    """并查集逐行合并连通域，返回图像坐标下的 [x1,y1,x2,y2]。"""
    import numpy as np
    parent, boxes, counts = [], [], []
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    previous = []
    for y, row in enumerate(mask):
        edges = np.flatnonzero(np.diff(np.pad(row.astype('int8'), (1,1))))
        current = []
        for x1, x2 in zip(edges[::2], edges[1::2]):
            links = [root(i) for a, b, i in previous if a < x2 and b > x1]
            if links:
                i = links[0]
                for j in set(links[1:]):
                    if j != i:
                        parent[j] = i
                        boxes[i] = [min(boxes[i][0],boxes[j][0]), min(boxes[i][1],boxes[j][1]), max(boxes[i][2],boxes[j][2]), max(boxes[i][3],boxes[j][3])]
                        counts[i] += counts[j]
            else:
                i = len(parent); parent.append(i); boxes.append([x1,y,x2,y+1]); counts.append(0)
            boxes[i] = [min(boxes[i][0],x1), min(boxes[i][1],y), max(boxes[i][2],x2), y+1]
            counts[i] += int(x2-x1)
            current.append((x1,x2,i))
        previous = current
    result = []
    for i, (x1,y1,x2,y2) in enumerate(boxes):
        if parent[i] == i and x2-x1 >= min_w and y2-y1 >= min_h and counts[i] >= min_px:
            result.append([int(left+x1), int(top+y1), int(left+x2), int(top+y2)])
    return result


def _panels(image, left, bottom):
    """白/绿气泡底（文字消息）。排除灰色昵称、头像、时间戳。"""
    import numpy as np
    arr = np.asarray(image.convert('RGB'), dtype='int16')[72:bottom, left:image.width-70]
    r, g, b = arr[:,:,0], arr[:,:,1], arr[:,:,2]
    mask = ((r >= 248) & (g >= 248) & (b >= 248)) | ((g > 180) & (g-r > 30) & (g-b > 30))
    return _components(mask, left)


def _photo_panels(image, left, bottom, min_side=56):
    """图片/表情包消息：没有白底气泡，底就是图片本身。

    白/绿掩码永远认不出它，于是"对方发了张图"对机器人根本不存在
    （2026-10-17 实测：群里发了一张图，抽到的气泡里一条都没有）。
    保守做法：只在白/绿气泡配不上头像行时才用它，且要求成片足够大
    （滤掉时间戳、昵称这类小字）。
    """
    import numpy as np
    arr = np.asarray(image.convert('RGB'), dtype='int16')[72:bottom, left:image.width-70]
    r, g, b = arr[:,:,0], arr[:,:,1], arr[:,:,2]
    bg = (np.abs(r-237) < 14) & (np.abs(g-237) < 14) & (np.abs(b-237) < 14)
    bubble = ((r >= 248) & (g >= 248) & (b >= 248)) | ((g > 180) & (g-r > 30) & (g-b > 30))
    # 只认"真有内容"的像素（彩色或明显偏暗），否则聊天底色的细微渐变会把
    # 一整行背景连成一大块，抽出来的图片框比图片本身宽好几倍。
    colorful = (arr.max(axis=2) - arr.min(axis=2)) > 24
    dark = arr.mean(axis=2) < 205
    mask = (~bg) & (~bubble) & (colorful | dark)
    return _components(mask, left, min_w=min_side, min_h=min_side,
                       min_px=min_side * min_side // 2)


def extract_messages(image, save_dir=None):
    # Width changes are not proportional scaling: sidebar and input toolbar have fixed sizes.
    if image.size not in {(980,710), (1021,740)}:
        raise ValueError('未验证的窗口尺寸: %dx%d' % image.size)
    sidebar = 283 if image.width == 1021 else 273
    bottom = image.height - 156
    panels = _panels(image, sidebar+64, bottom)
    photos = _photo_panels(image, sidebar+64, bottom)
    # 头像列在不同布局里位置不同：私聊气泡贴左缘（x≈305），而**群聊**气泡因为顶部
    # 有发送者昵称会整体右移（实测 x≈355）。写死一个 x 会让群聊一条消息都读不出来
    # （2026-10-17 实测：「人机」群 visible=0，而白/绿气泡其实已经正确识别出 3 条）。
    # 做法：按候选列依次试，用第一个"真能找到头像"的那列，避免同一行被重复计入。
    marks = []
    for direction, xs in (('in', (sidebar+22, sidebar+57, sidebar+72, sidebar+87)),
                          ('out', (image.width-60, image.width-95))):
        ambiguous = False
        for x in xs:
            rows = avatar_rows(image, x)
            if not rows:
                continue
            # 列表宽度可被用户拖动：第一候选列可能仍在列表内部。
            # 这种列整段都是非背景色，不能当头像；先试后续候选列，
            # 全部候选列都不可信时才拒绝，绝不接受超高的伪头像。
            if any(b-a > 45 for a,b in rows):
                ambiguous = True
                continue
            marks.extend((a,b,direction) for a,b in rows)
            break
        else:
            if ambiguous:
                raise ValueError('头像行检测不明确')
    result = []
    used = set()
    used_photo = set()
    claimed = []
    for a,b,direction in sorted(marks):
        # 方向判定看**气泡右缘**，不看左缘：群聊里对方的气泡因为头像+昵称会整体右移
        # （实测左缘 x≈405，而私聊是 x≈300），用左缘阈值会把群消息全判成"发出去的"，
        # 于是三条消息一条都留不下（2026-10-17 实测「人机」群 visible=0 的真因）。
        candidates = [(i,box) for i,box in enumerate(panels) if i not in used
                      and a-4 <= box[1] <= a+40
                      and (box[2] <= image.width-200 if direction == 'in'
                           else box[2] >= image.width-200)]
        if len(candidates) == 1:
            i, box = candidates[0]; used.add(i)
        else:
            # 白/绿气泡配不上这一行：可能是图片/表情包消息（底就是图片本身）
            alt = [(i,box) for i,box in enumerate(photos) if i not in used_photo
                   and a-4 <= box[1] <= a+40
                   and (box[0] <= sidebar+90 if direction == 'in' else box[2] >= image.width-90)]
            if len(alt) != 1: continue
            i, box = alt[0]; used_photo.add(i)
        if box[3] >= bottom-2: continue  # may be clipped at viewport edge
        bubble = image.crop(box)
        digest = hashlib.sha256(bubble.tobytes()).hexdigest()
        crop_path = ''
        if save_dir is not None:
            d=Path(save_dir);d.mkdir(parents=True,exist_ok=True)
            crop_path=str(d/('bubble-%s.png' % digest[:12]));bubble.save(crop_path)
        result.append({'direction':direction,'kind':'unread','text':'','description':'',
                       'at_me':False, 'bbox':box,'signature':direction+':'+digest,'crop_path':crop_path})
        claimed.append(box)
    # 没被任何头像行认领的大图片块：图片被滚到顶、头像行抽不出来时就是这种情况，
    # 方向按左右位置判断（左贴边=收到，右贴边=自己发的）。以前这种图整条消失。
    for i, box in enumerate(photos):
        if i in used_photo:
            continue
        if any(not (box[2] <= c[0] or box[0] >= c[2] or box[3] <= c[1] or box[1] >= c[3])
               for c in claimed):
            continue
        if box[3] >= bottom - 2:
            continue
        direction = 'in' if box[0] <= sidebar + 90 else ('out' if box[2] >= image.width - 90 else None)
        if direction is None:
            continue
        bubble = image.crop(box)
        digest = hashlib.sha256(bubble.tobytes()).hexdigest()
        crop_path = ''
        if save_dir is not None:
            d = Path(save_dir); d.mkdir(parents=True, exist_ok=True)
            crop_path = str(d / ('bubble-%s.png' % digest[:12])); bubble.save(crop_path)
        result.append({'direction': direction, 'kind': 'unread', 'text': '', 'description': '',
                       'at_me': False, 'bbox': box, 'signature': direction + ':' + digest,
                       'crop_path': crop_path})
        claimed.append(box)
    return result

