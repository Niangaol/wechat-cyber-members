"""会话列表导航：OCR 定位目标会话→点击切换→标题核验。
所有点击基于主窗口坐标；标题不符时拒绝任何后续操作（防发错窗）。"""
import hashlib, logging, re, time
from wechat_ui import normalize, SafetyError, title_matches
from chat_anchors import title_anchor_matches, find_list_anchor


def avatar_rows(image):
    """用头像色块定位会话列表的行（纯 numpy，不 OCR），返回 [(top, bottom)]。

    头像在图标的左边一列（x 78–110），每个会话一行、头像比文字更稳定：
    用它的纵向色块代替"按名字 OCR 找行"，避免中文昵称被 OCR 读错后彻底找不到。
    """
    import numpy as np
    a = np.asarray(image.convert('RGB'), dtype='int16')
    strip = a[65:image.height - 12, 78:110]
    marked = (((strip.max(2) - strip.min(2)) > 30) | (strip.mean(2) < 180)).sum(1) >= 8
    ys = np.flatnonzero(marked)
    runs = []
    for y in ys:
        if runs and int(y) - runs[-1][-1] <= 5:
            runs[-1].append(int(y))
        else:
            runs.append([int(y)])
    out = []
    for run in runs:
        if 20 <= run[-1] - run[0] <= 52:      # 头像高度约 36–45px
            out.append((65 + run[0], 65 + run[-1]))
    return out


def avatar_key(image, center_y, rows=None):
    """头像的像素指纹：用来把列表行和"哪个会话"绑定，不依赖 OCR 名字。

    会先把 y 吸附到所在头像行的中心再取块：否则"文字行中心"和"头像中心"
    算出来的指纹会差几个像素、对不上（缓存永远命中不了）。
    固定缩到 16×16，选择态/未读态都不影响头像本身。
    """
    import hashlib
    runs = rows if rows is not None else avatar_rows(image)
    for (top, bot) in runs:
        if top - 8 <= center_y <= bot + 8:
            center_y = (top + bot) // 2
            break
    crop = image.crop((78, max(0, center_y - 18), 110, min(image.height, center_y + 18)))
    return hashlib.sha1(crop.convert('RGB').resize((16, 16)).tobytes()).hexdigest()[:16]


def row_y_by_avatar(image, key):
    """在可见列表里按头像指纹找会话行，返回行中心 y（纯 numpy+hash，不 OCR）。

    比"记住上次的 y"稳：列表按最近活跃重排，y 会漂；头像不会。
    """
    if not key:
        return None
    runs = avatar_rows(image)
    for (top, bot) in runs:
        y = (top + bot) // 2
        if avatar_key(image, y, runs) == key:
            return y
    return None


def row_band_sig(image, y):
    """会话行的二值化像素签名：名字行 + 预览 + 右侧未读角标，去掉选中高亮底色。

    resident（判断行变没变）和 navigator（直接按记忆位置点）共用同一实现，
    保证"看到的行"和"点下去的行"是同一个判据。
    """
    band = image.crop((121, max(0, y - 16), 300, min(image.height, y + 34)))
    mask = band.convert('L').point(lambda p: 0 if p < 150 else 255)
    return mask.tobytes()


def row_changed(prev, sig, tolerance=0.02):
    """行是否真的变了：动画/反锯齿噪声不算，超过 tolerance 比例的像素不同才算。"""
    if prev is None or len(prev) != len(sig):
        return True
    diff = sum(1 for a, b in zip(prev, sig) if a != b)
    return diff > max(8, int(len(sig) * tolerance))


def ocr_tsv(ui, image):
    """带 bounding box 的 OCR（tesseract TSV 模式）。返回 [(text, x, y, w, h), ...]"""
    image = image.convert('RGB').resize((image.width*3, image.height*3))
    import io
    out = io.BytesIO(); image.save(out, 'PNG')
    raw = ui.run(['tesseract', 'stdin', 'stdout', '-l', 'chi_sim+eng', '--psm', '6', 'tsv'],
                 out.getvalue(), timeout=25).decode('utf-8', 'ignore')
    words = []
    for line in raw.splitlines()[1:]:
        parts = line.split('\t')
        if len(parts) < 12:
            continue
        text = parts[11].strip()
        if not text:
            continue
        try:
            x, y, w, h = int(parts[6])//3, int(parts[7])//3, int(parts[8])//3, int(parts[9])//3
        except ValueError:
            continue
        words.append((text, x, y, w, h))
    return words


def _list_match(name, text):
    """列表名匹配（微信列表常截断显示「很帅...」）：去省略号后做包含/前缀匹配。"""
    n = re.sub(r'[…\.、,，;；]', '', normalize(name))
    t = re.sub(r'[…\.、,，;；]', '', normalize(text))
    if not n or not t:
        return False
    if n in t or t in n:
        return True
    k = min(len(n), len(t))
    return k >= 2 and n[:k] == t[:k]


def template_match_list(ui, image, template_path, thresh=0.90):
    """模板匹配定位会话项（OCR 对中文名+头像干扰不可靠时的主路线）。
    在列表区域滑 y 算归一化互相关，返回最佳 (score, y中心) 或 None。"""
    if not template_path.exists():
        return None
    try:
        import numpy as np
        from PIL import ImageOps
        region = image.crop((60, 60, 340, 555))
        r = np.asarray(ImageOps.grayscale(region), dtype='float32')
        t = np.asarray(ImageOps.grayscale(Image.open(template_path)), dtype='float32')
        th, tw = t.shape
        if r.shape[0] < th or r.shape[1] < tw:
            return None
        t_n = t - t.mean()
        t_den = float((t_n * t_n).sum()) or 1.0
        best, by = -2.0, -1
        for y in range(0, r.shape[0] - th + 1, 2):
            win = r[y:y + th, :tw]
            w_n = win - win.mean()
            den = float((w_n * w_n).sum()) or 1.0
            score = float((w_n * t_n).sum()) / ((den * t_den) ** 0.5)
            if score > best:
                best, by = score, y
        if by >= 0 and best >= thresh:
            return best, 60 + by + th // 2
        return None
    except Exception:
        return None


LINE_TOL = 10        # 同一行的 y 容差（像素）
NAME_X_MAX = 175    # 名称列右边界：x 起点更靠右的是时间戳/未读徽标，不属于名称
FUZZY_MIN = 0.75    # 名称至少 3 字才允许模糊匹配（OCR 常把生僻字认错）
FUZZY_BLOCK = 0.7   # 最长公共块占名称长度的比例（比整体相似度更抗头像/时间戳噪声）


def merge_list_lines(words):
    """把 OCR 词块按 y 聚成"列表行"，返回 [(y_center, 合并文本, 最左 x)]。

    不聚行的话单个汉字永远匹配不上完整昵称——实测中文昵称会被
    tesseract 拆成 很/帅/的/年/料 五个词块（「糕」还被认成「料」）。
    """
    rows = []
    for text, x, y, w, h in sorted(words, key=lambda t: (t[2], t[1])):
        if x >= NAME_X_MAX:
            continue
        cy = y + h / 2.0
        for row in rows:
            if abs(row['cy'] - cy) <= LINE_TOL:
                row['parts'].append((x, text, w))
                row['cy'] = (row['cy'] * row['n'] + cy) / (row['n'] + 1)
                row['n'] += 1
                break
        else:
            rows.append({'cy': cy, 'n': 1, 'parts': [(x, text, w)]})
    out = []
    for row in rows:
        parts = sorted(row['parts'])
        text = ''.join(t for _, t, _ in parts)
        left, right = parts[0][0], max(x + w for x, _, w in parts)
        out.append((row['cy'], text, (left + right) / 2.0))
    return out


def _line_matches(name_norm, line_text):
    """整行文本是否就是这个会话名：先精确/前缀，再对长名做模糊。

    行文本里混着头像噪声（OCR 把头像读成 "AQ"/"RR"）、省略号和时间戳，
    所以先剥掉非文字字符，再用"最长公共块"判断，比整体相似度抗噪：
    「AQAgent聊天测」对「Agent聊天测试群」最长公共块 8 字 ≥ 0.7×10。
    """
    t = re.sub(r'[^0-9A-Za-z\u4e00-\u9fff]', '', line_text or '')
    if not t:
        return False
    # 这里是"找行"，不是"授权"：大小写放开（OCR 大小写不稳，授权在点开后的标题核验里）。
    name_norm, t = name_norm.lower(), t.lower()
    if t == name_norm or (len(t) >= 2 and (name_norm.startswith(t) or t.startswith(name_norm))):
        return True
    # 短名字（2-3 字，比如群名"人机"）必须能在**子串**位置匹配：
    # 列表行里混着头像噪声，OCR 出来是"oae人机"，名字不在行首。
    # 命中后仍要过"唯一候选 + 点开后完整标题核验"两道关，所以这里放宽不会点错人。
    if 2 <= len(name_norm) <= 3 and name_norm in t:
        return True
    if len(name_norm) < 3 or len(t) < 3:
        return False
    from difflib import SequenceMatcher
    matcher = SequenceMatcher(None, name_norm, t)
    block = matcher.find_longest_match(0, len(name_norm), 0, len(t))
    if block.size >= max(3, int(len(name_norm) * FUZZY_BLOCK)):
        return True
    if matcher.ratio() >= FUZZY_MIN:
        return True
    # 行首前缀：微信列表把「名字 + 时间 + 预览」粘成一行，OCR 后是
    # 「Deep...Yesterday」这种。名字一定在行首，所以拿行首前缀跟名字前缀比。
    # 2026-10-17 实测：新好友 Deepseek 因为这一条匹配不上，机器人一直看不见他的会话。
    # 命中后仍要"唯一候选 + 点开后标题核验"两道关，所以这里放宽不会点错人。
    low = 2 if len(name_norm) <= 3 else 4
    for cut in range(min(len(t), len(name_norm)), low - 1, -1):
        if name_norm.startswith(t[:cut]):
            return True
    return False


def find_chat_in_list(ui, image, name):
    """可见列表候选定位，不等于授权；重复候选拒绝，最终须完整标题核验。"""
    hit = find_list_anchor(name, image)
    if hit:
        return hit
    # 先看头像对应的名称行，避免把其他群的消息预览里的好友名当成会话。
    from direct_discovery import candidate_rows
    exact = [pos for text,pos in candidate_rows(ui,image) if title_matches(name,text,False)]
    if exact:
        return exact[0] if len(exact)==1 else None
    words = ocr_tsv(ui, image.crop((60, 60, 283, 555)))
    n = normalize(name)
    rows = []
    for cy, text, center_x in merge_list_lines(words):
        if not _line_matches(n, text):
            continue
        y = 60 + int(cy)
        if not any(abs(y - existing[1]) < 16 for existing in rows):
            rows.append((60 + int(center_x), y))
    if rows:
        return rows[0] if len(rows)==1 else None
    return None


class ChatNavigator:
    """仅在可见会话列表定位并点击；完整标题核验失败即中止。
    不输入搜索词、不操作剪贴板、不使用可能过期的坐标缓存。"""

    LIST_REGION = (60, 60, 340, 555)

    def __init__(self, ui):
        self.ui = ui
        self.pos_cache = {}   # name -> (x, y) 窗口相对坐标
        self.last_row_y = None  # 最近一次成功定位的列表行中心 y（"行没变就跳过"用）
        self._cur_title = (None, None)  # (当前会话名, 标题像素)：避免每次切换都 OCR 标题
        self._title_px = {}             # 会话名 -> 亲眼见过的标题像素（命中即免 OCR）
        self._rows = None     # 会话列表行缓存：一次 OCR 服务多个会话/多轮
        self._rows_sig = None # 缓存对应的侧栏像素签名（变了就重扫）

    def rows_for(self, image):
        """返回可见会话行 [(y_center, text, x_center)]，侧栏像素没变就不重复 OCR。

        只用于"该点哪一行"的便宜候选；点开后的完整标题核验照旧，点错会被否决，
        重试时改用精确名称行，所以复用不会降低安全性。
        """
        strip = image.crop((60, 60, 283, 555))
        sig = hashlib.sha1(strip.tobytes()).hexdigest()
        if self._rows is not None and self._rows_sig == sig:
            return self._rows
        words = ocr_tsv(self.ui, strip)
        self._rows = [(60 + cy, text, 60 + cx)
                      for cy, text, cx in merge_list_lines(words)]
        self._rows_sig = sig
        return self._rows

    def match_rows(self, rows, name):
        """在缓存的列表行里定位会话；必须唯一命中，多候选一律当没找到。"""
        n = normalize(name)
        hits = [(int(x), int(y)) for y, text, x in rows if _line_matches(n, text)]
        uniq = []
        for pos in hits:
            if not any(abs(pos[1] - q[1]) < 16 for q in uniq):
                uniq.append(pos)
        return uniq[0] if len(uniq) == 1 else None

    def scroll_list_top(self):
        """把会话列表滚到顶。

        列表按最近活跃排序：久没消息的会话会一直沉，最后滚出可视区。
        计划里要同时盯 2-3 个会话，这事迟早会撞上，所以找不到目标时先滚到顶再找。
        鼠标只落在列表区域里滚轮，不点输入框、不碰草稿。
        """
        ax, ay = getattr(self.ui, 'last_abs', (0, 0))
        x = ax + (self.LIST_REGION[0] + self.LIST_REGION[2]) // 2
        y = ay + (self.LIST_REGION[1] + self.LIST_REGION[3]) // 2
        self.ui.run(['xdotool', 'mousemove', str(x), str(y)])
        for _ in range(6):          # 列表可视高度约 500px，6 格足够到顶
            self.ui.run(['xdotool', 'click', '4'])
            time.sleep(0.05)
        time.sleep(0.25)
        return self.ui.capture()

    def scroll_list_page(self, down=True, notches=3):
        """在列表区域里翻一页（只滚鼠标，不点任何东西）。down=False 往上翻。"""
        ax, ay = getattr(self.ui, 'last_abs', (0, 0))
        x = ax + (self.LIST_REGION[0] + self.LIST_REGION[2]) // 2
        y = ay + (self.LIST_REGION[1] + self.LIST_REGION[3]) // 2
        self.ui.run(['xdotool', 'mousemove', str(x), str(y)])
        for _ in range(notches):
            self.ui.run(['xdotool', 'click', '5' if down else '4'])
            time.sleep(0.05)
        time.sleep(0.45)      # 列表滚动有惯性：等它停稳再截图，否则坐标是中间态
        return self.ui.capture()

    def find_by_scrolling(self, name, pages=4):
        """可见区找不到时有界地滚动查找，返回 (pos, image)。

        为什么需要：微信把刚聊过的会话顶到最上面，其他会话会被挤到可视区之外，
        只滚到顶是找不到**更下面**的会话的（2026-10-17 实测"人机"群时好时坏）。
        滚动是纯鼠标操作：不点输入框、不输入任何字、不碰剪贴板，所以比"搜索框盲搜"安全得多。
        找不到就把列表还原到顶部，不给下一次留个奇怪的滚动位置。
        """
        image = self.scroll_list_top()
        last = image
        for _ in range(max(1, pages)):
            # 每页先用便宜的列表行 OCR 找（0.6s），找不到才在最后一页用精确名称行兜底。
            pos = self.match_rows(self.rows_for(image), name)
            if pos is not None:
                return pos, image
            last = image = self.scroll_list_page(down=True)
        pos = find_chat_in_list(self.ui, last, name)
        if pos is not None:
            return pos, last
        return None, self.scroll_list_top()   # 同上：交回当前真实画面

    def switch_to(self, name, use_cache=True):
        """按当前画面重新定位会话行；可见区找不到时有界滚动查找，仍不输入搜索词。

        可选 hint（通过 self.pending_hint 传入，一次性）：(row_y, row_sig) 是上次
        定位到这一行时的位置与像素签名。当前帧这一行像素和记忆一致 → 列表没动过，
        直接点它（点完的标题核验照旧兜底），省掉 1–3 秒的整表 OCR；不一致就走
        原来的精确查找。用属性传而不是参数，是为了让测试里的假 navigator 不受影响。
        """
        hint = getattr(self, 'pending_hint', None)
        self.pending_hint = None
        last_title = ''
        self.last_row_y = None
        t_start = time.time()
        for attempt in range(3):
            # 每轮都重新截图：列表会因为别处来了新消息而重排，拿旧坐标点会点错行。
            image = self.ui.capture()       # 顺带拿到 wid 和窗口绝对位置
            if self._matches_title(image, name):
                self._note_switch(name, time.time() - t_start, attempt + 1, 'already')
                return image                # 已在目标会话，不点击、不触碰现有草稿
            pos = None
            source = 'none'
            if (attempt == 0 and hint and hint[0] is not None and hint[1]
                    and not row_changed(hint[1], row_band_sig(image, hint[0]))
                    and (len(hint) < 3 or not hint[2]
                         or avatar_key(image, int(hint[0])) == hint[2])):
                # 行像素一致 **且** 头像指纹一致才直接点：后者防"列表滚动后同一
                # 位置换成了别的会话"。注意只做校验、不做全场头像查找——实测
                # "先按头像全场找"在目标不在可视区时要多滚一轮，反而更慢
                #（三轮基准 23s → 80s），所以这里保持原来的查找顺序。
                pos = (160, int(hint[0]))
                source = 'hint'
            # 定位顺序按成本从低到高：像素锚点 → 行缓存候选 → 整表扫描。
            # 缓存点错时标题核验会否决，重试改用精确名称行，不会把错位置当成授权。
            if pos is None:
                pos = find_list_anchor(name, image)
                if pos is not None:
                    source = 'anchor'
            if pos is None and attempt > 0:
                pos = find_chat_in_list(self.ui, image, name)
                if pos is not None:
                    source = 'full'
            if pos is None:
                pos = self.match_rows(self.rows_for(image), name)
                if pos is not None:
                    source = 'rows'
            if pos is None:
                pos = find_chat_in_list(self.ui, image, name)
                if pos is not None:
                    source = 'full'
            if pos is None:
                image = self.scroll_list_top()
                if self._matches_title(image, name):
                    return image
                pos = find_chat_in_list(self.ui, image, name)
            if pos is None:
                # 有界滚动再找一遍（只滚鼠标）；仍找不到就放弃，绝不输入搜索词
                pos, image = self.find_by_scrolling(name)
            if pos is None:
                if attempt == 2:
                    raise SafetyError('列表滚动查找后仍未唯一命中；不输入搜索词、不覆盖草稿')
                continue
            # 注意：不要在这里再补一帧"临点复核"。实测滚动查找刚结束时列表可能
            # 正在归位，补拍的帧里头像常常已经不在原处，沿用旧坐标就会点到隔壁行
            # （很帅的年糕 点成 豆包，重试三次全废）。位置按找到它的那一帧点，
            # 点错由点击后的标题核验兜底。
            self.last_row_y = int(pos[1])
            ax, ay = getattr(self.ui, 'last_abs', (0, 0))
            self.ui.run(['xdotool', 'mousemove', str(ax + pos[0]), str(ay + pos[1])])
            self.ui.run(['xdotool', 'click', '1'])
            time.sleep(0.35)          # 刚够界面换标题；慢了会被下面的标题核验兜住
            image = self.ui.capture()
            if self._matches_title(image, name):
                self._note_switch(name, time.time() - t_start, attempt + 1, 'ok')
                return image
            # 也可能是"点击后标题还没画完"（实测 OCR 会读成 四| 之类）：
            # 补一帧再判，命中就不用重试，只有真点错才走下面的重试路径。
            time.sleep(0.25)
            image = self.ui.capture()
            if self._matches_title(image, name):
                self._note_switch(name, time.time() - t_start, attempt + 1, 'ok_repaint')
                return image
            last_title = self.current_title(image)
            self._rows = None     # 点错行说明列表和缓存对不上：下次重新 OCR
            logging.info('switch_title_mismatch name=%s attempt=%d got=%r source=%s pos=%s',
                         name, attempt, last_title[:40], source, pos)
        raise SafetyError('切换后标题未精确匹配 %s（重试 3 次，最后读到 %r）'
                          % (name, last_title[:30]))

    def _note_switch(self, name, elapsed, attempts, reason='ok'):
        """慢切换留痕：一次性定位 3–4 秒还能接受，反复重试就要看得见原因。"""
        if elapsed > 2.0:
            logging.info('switch_slow name=%s elapsed=%.2fs attempts=%d %s',
                         name, elapsed, attempts, reason)

    @staticmethod
    def _title_pixels(image):
        return image.crop((283, 20, 700, 61)).convert('RGB').tobytes()

    def _remember_title(self, name, px):
        self._cur_title = (name, px)
        self._title_px[name] = px

    def _matches_title(self, image, name):
        px = self._title_pixels(image)
        # 这一帧标题像素 == 上次亲眼确认过该会话的标题像素：免 OCR 直接放行。
        # 实测这条能挡掉"刚点完标题还没画完，OCR 读成 四| 然后白白重试一次"。
        if self._title_px.get(name) is not None and self._title_px[name] == px:
            self._cur_title = (name, px)
            return True
        if self._cur_title[1] is not None and self._cur_title[1] == px:
            return normalize(self._cur_title[0] or '') == normalize(name)
        if title_anchor_matches(name, image):
            self._remember_title(name, px)
            return True
        title = self.current_title(image)
        is_group = normalize(name) in {normalize(g) for g in self.ui.cfg.get('group_whitelist', [])}
        if title_matches(name, title, is_group):
            self._remember_title(name, px)
            return True
        if hasattr(self.ui, "title_texts") and any(
                title_matches(name, t, is_group) for t in self.ui.title_texts(image)):
            self._remember_title(name, px)
            return True
        # 仅原始登记目标可使用人工核验模板；其他会话不能借用。
        from PIL import Image
        from pathlib import Path
        anchor = Path(__file__).resolve().parent.parent / 'config' / 'target-title.png'
        if normalize(name) == normalize(self.ui.cfg.get('target_chat', '')) and anchor.exists():
            with Image.open(anchor) as template:
                return template.convert('RGB').tobytes() == image.crop((283, 20, 700, 61)).convert('RGB').tobytes()
        return False

    def current_title(self, image=None):
        image = image if image is not None else self.ui.capture()
        return normalize(self.ui.ocr(image.crop((283, 20, 700, 61)), 7))
