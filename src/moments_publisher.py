"""朋友圈发布/互动执行器：UI 流程 + 每步截图验证。

2026-10-16 实机标定后的关键认知（都写进流程了）：
1. 朋友圈是**独立窗口**（标题 Moments，573x573），不在主窗口内容区——
   截图和按键都必须发给 Moments 窗口，不是 ui.capture() 抓的主窗口。
2. 点相机图标直接弹 Qt 文件对话框（没有"从相册选择"中间菜单）。
3. 文件对话框里键入完整路径后**按 Enter 确认**比点 Open 可靠
   （点 Open 有时只关对话框退回信息流）。
4. Enter 确认后编辑页的文字输入框**自动获得焦点**，直接粘贴即可。
5. Qt 文件对话框吃 --window 直送（XSendEvent）的点击/按键；
   Moments 窗口吃 XTEST。
坐标全部集中在 COORDS；未标定的动作抛 NotImplementedError，绝不瞎点。

2026-10-16 晚间互动（赞/评）标定认知：
6. 信息流里每张动态卡片底部右侧有个 ··· 小按钮；它弹出的菜单是独立 X 窗口
   （标题 wechat，实测 274x38），Like 在左半、Comment 在右半——按窗口尺寸
   动态找，不用固定坐标。
7. 评论框固定在 Moments 窗口底部（不随卡片变）：输入框 + 表情图标 + Send；
   Send 空输入时灰色禁用、有内容才变绿。Escape 可无痕退出（不发送）。
8. ··· 按钮位置随卡片内容高度变化，用像素扫描定位（247 灰底 + 双点的
   32x20 小方块），配合 OCR 核验卡片作者名后才点——绝不对没核实的卡片下手。
"""
import io
import re
import time

from PIL import Image

from moments_safe import sanitize_for_moment
from wechat_ui import SafetyError, normalize

# 登录后在 Moments 窗口实测标定；None = 未标定
COORDS = {
    'moments_icon': None,       # 主窗口左侧边栏光圈图标（打开朋友圈面板）
    'camera_icon': None,        # Moments 窗口顶栏相机图标（发布入口）
    'file_path_input': None,    # Qt 文件对话框 File name 输入框
    'file_open_button': None,   # 文件对话框 Open 按钮（备用，Enter 更可靠）
    'text_input': None,         # 编辑页 Say something 输入行
    'publish_button': None,     # 编辑页绿色 Post 按钮
    'moment_more': None,        # 动态右侧"···"（相对动态卡片的位置）
    'menu_like': None,          # ···弹菜单里的"赞"
    'menu_comment': None,       # ···弹菜单里的"评论"
    'comment_input': None,      # 评论输入框
    'comment_send': None,       # 评论发送按钮
}

MOMENTS_TITLE = '^Moments$'


class PublisherError(RuntimeError):
    pass


class MomentsPublisher:
    """所有点击基于实测坐标；每步后截图验证状态变化。"""

    def __init__(self, ui, coords=None):
        self.ui = ui
        self.coords = dict(COORDS)
        if coords:
            self.coords.update({k: v for k, v in coords.items() if v})
        self.moments_wid = None

    # ---------- 基础 ----------
    def _need(self, *keys):
        missing = [k for k in keys if not self.coords.get(k)]
        if missing:
            raise NotImplementedError('坐标未标定: %s（登录后先标定再执行）' % ','.join(missing))

    def _sh(self, args, timeout=20):
        """跑 xdotool/import（带上 ui 的 DISPLAY 环境）。"""
        return self.ui.run(args, timeout=timeout)

    def find_moments_window(self):
        """定位 Moments 独立窗口；没开返回 None。

        不依赖窗口名：实测窗口名会损坏（变成 UTF8 转换错误文案，2026-10-16）。
        两级匹配取并集：① 名字含 Moments（历史路径）；② 可见 wechat 类窗口中
        573±10 宽、560-760 高的面板（Moments 固定宽 573）。并集必须恰好一个。
        """
        candidates = set()
        try:
            # 必须 --onlyvisible：朋友圈窗口关掉后仍留在窗口树里（未映射），
            # 只按名字搜会误判成"面板已开"，接着对着隐藏窗口点相机图标，
            # 最后卡在"文件对话框 10 秒内没出现"（2026-10-16 实录）。
            out = self._sh(['xdotool', 'search', '--onlyvisible', '--name',
                            MOMENTS_TITLE]).decode('utf-8', 'ignore')
            candidates |= {t for t in out.split() if t.isdigit()}
        except Exception:
            pass
        try:
            out = self._sh(['xdotool', 'search', '--onlyvisible', '--class', 'wechat']).decode(
                'utf-8', 'ignore')
        except Exception:
            out = ''
        for wid in [t for t in out.split() if t.isdigit()]:
            try:
                info = self._sh(['xdotool', 'getwindowgeometry', '--shell', wid]).decode(
                    'utf-8', 'ignore')
                w = re.search(r'WIDTH=(\d+)', info)
                h = re.search(r'HEIGHT=(\d+)', info)
                if w and h and 560 <= int(w.group(1)) <= 590 and 560 <= int(h.group(1)) <= 760:
                    candidates.add(wid)
            except Exception:
                continue
        if len(candidates) == 1:
            self.moments_wid = candidates.pop()
            return self.moments_wid
        if candidates:
            raise PublisherError('找到 %d 个疑似 Moments 窗口，拒绝猜测' % len(candidates))
        return None

    def _shot(self):
        """截 Moments 窗口（不是主窗口）。"""
        wid = self.find_moments_window()
        if not wid:
            raise PublisherError('Moments 窗口未找到（朋友圈面板没打开）')
        data = self._sh(['import', '-window', wid, 'png:-'], timeout=40)
        return Image.open(io.BytesIO(data)).convert('RGB')

    def _key(self, key):
        """发按键给 Moments 窗口（AppEx 忽略 --window 的 XSendEvent 按键，必须 XTEST）。"""
        wid = self.moments_wid or self.find_moments_window()
        if not wid:
            raise PublisherError('找不到 Moments 窗口，无法发送按键')
        self._sh(['xdotool', 'windowfocus', wid])
        self._sh(['xdotool', 'key', '--clearmodifiers', key])

    def _click(self, key):
        """点击 Moments 窗口内控件：坐标为窗口相对，按实时原点换算（窗口可移动）。"""
        self._need(key)
        rx, ry = self.coords[key]
        ox, oy = self._win_origin()
        self._sh(['xdotool', 'mousemove', str(ox + rx), str(oy + ry)])
        time.sleep(0.2)
        self._sh(['xdotool', 'click', '1'])
        time.sleep(0.8)

    def _window_ids(self, pattern):
        try:
            out = self._sh(['xdotool', 'search', '--name', pattern]).decode('utf-8', 'ignore')
        except Exception:
            return []
        return [t for t in out.split() if t.isdigit()]

    def _wait_window(self, pattern, timeout):
        for _ in range(timeout):
            ids = self._window_ids(pattern)
            if ids:
                return ids[0]
            time.sleep(1.0)
        return None

    # ---------- 朋友圈面板 ----------
    def raise_moments(self, wid):
        """把朋友圈窗口抬到最上层。

        面板关掉后窗口仍留在窗口树里（mapped 但被主窗口盖住），xdotool 的
        --onlyvisible 也照样能搜到。此时点"相机图标"其实点在主窗口上，
        整条发布链路会卡在"文件对话框 10 秒内没出现"（2026-10-16 实录）。
        """
        for args in (['xdotool', 'windowmap', str(wid)],
                     ['xdotool', 'windowraise', str(wid)],
                     ['xdotool', 'windowactivate', '--sync', str(wid)]):
            try:
                self._sh(args, timeout=10)
            except Exception:
                pass
        time.sleep(0.6)

    def moments_is_front(self, wid):
        """朋友圈窗口是否真的显示在最上层：和整屏同位置像素对比。

        拿不到证据时返回 True（不阻断），因为后面每次点击仍有窗口/坐标保护。
        """
        try:
            x, y = self._win_origin(wid)
            shot = self._shot()
            root = Image.open(io.BytesIO(
                self._sh(['import', '-window', 'root', 'png:-'], timeout=40))).convert('RGB')
        except Exception:
            return True
        box = (max(0, x), max(0, y),
               min(root.width, x + shot.width), min(root.height, y + shot.height))
        if box[2] - box[0] < 50 or box[3] - box[1] < 50:
            return False
        import numpy as np
        a = np.asarray(root.crop(box).convert('L'), dtype='int16')
        b = np.asarray(shot.convert('L').crop((0, 0, a.shape[1], a.shape[0])), dtype='int16')
        return float(abs(a - b).mean()) < 18

    def open_moments_panel(self):
        """确保 Moments 独立窗口打开且在最上层；已开则不重复点图标（图标是开关）。"""
        wid = self.find_moments_window()
        if wid:
            self.raise_moments(wid)
            if not self.moments_is_front(wid):
                raise PublisherError('朋友圈窗口抬不到最上层，拒绝盲点；请人工处理')
            return wid
        self._need('moments_icon')
        self.ui.capture()   # 拿主窗口实时原点（顺带验证登录与固定几何）
        ax, ay = getattr(self.ui, 'last_abs', (0, 0))
        rx, ry = self.coords['moments_icon']
        self._sh(['xdotool', 'mousemove', str(ax + rx), str(ay + ry)])
        time.sleep(0.2)
        self._sh(['xdotool', 'click', '1'])
        for _ in range(15):
            time.sleep(1.0)
            if self.find_moments_window():
                return self.moments_wid
        raise PublisherError('点了朋友圈图标但 Moments 窗口 15 秒内没出现')

    def _close_stale_dialog(self):
        """清掉上一次失败残留的文件对话框。

        它不关掉的话会一直抢焦点：纯文字动态直接粘贴会把文案打进 File name 栏
        （2026-10-17 实录：对话框从上次失败一直挂在那里）。
        """
        for _ in range(2):
            try:
                wid = self._wait_window('^Open$', 1)
            except Exception:
                return
            if not wid:
                return
            try:
                self._sh(['xdotool', 'windowclose', str(wid)], timeout=10)
            except Exception:
                pass
            time.sleep(1.0)

    # ---------- 发布 ----------
    def publish(self, text, image_path=None):
        """走到"待发布"状态：选图 + 粘贴文案 + 截图对比。**不点发表按钮**。

        返回编辑页截图；调用方核验后自己决定何时点 publish_button。
        """
        self._need('text_input')
        self._close_stale_dialog()
        self.open_moments_panel()
        if image_path:
            # 只有真的要配图才点相机图标：纯文字动态点它只会弹一个空文件框，
            # 把焦点抢走，后面粘贴的文案会打进对话框（2026-10-17 实录）。
            self._need('camera_icon')
            self._click('camera_icon')
            time.sleep(2.0)
            self._need('file_path_input')
            dialog = self._wait_window('^Open$', 10)
            if not dialog:
                raise PublisherError('点了相机图标但文件对话框 10 秒内没出现')
            self._dialog_type_path(dialog, image_path)
            # Enter 确认：焦点在 File name 字段，直接全局回车（比点 Open 可靠）
            self._sh(['xdotool', 'key', '--clearmodifiers', 'Return'])
            self._wait_window_gone('^Open$', 15)
            time.sleep(2.0)

        # 编辑页：Enter 确认后输入框自动带焦点（2026-10-16 标定实测）。
        # 不要点输入行：AppEx 的输入辅助表面会盖在窗口上吃掉点击并抢走键盘焦点，
        # 导致粘贴无效（实测两次失败均由此引起）。直接粘贴即可。
        # 微信会把上次没发出去的草稿带回编辑页；先全选删除，保证只可能有一份文案
        self._key('ctrl+a')
        self._sh(['xdotool', 'key', '--clearmodifiers', 'Delete'])
        time.sleep(0.3)
        self.ui.clipboard_write(text)
        self._key('ctrl+v')
        time.sleep(1.0)
        # 判据是"OCR 能读到目标文案"，不是"画面有没有变化"：缩略图早就加载完时
        # 文案粘贴完也可能两帧完全一致（实测 2026-10-16 因此误报失败）。
        waited = 0.0
        while waited < 8.0:
            shot = self._shot()
            if self.text_present(text, shot):
                return shot
            time.sleep(1.0)
            waited += 1.0
        raise PublisherError('粘贴后编辑页读不到目标文案（粘贴没生效/内容不符），拒绝继续')

    def text_present(self, text, image=None, region=(100, 50, 520, 260)):
        """OCR 编辑页确认目标文案真的在里面（发出去就删不掉了，必须先自证）。"""
        import re
        image = image if image is not None else self._shot()
        try:
            crop = image.crop(region)
            seen = self.ui.ocr(crop, 6)
        except Exception:
            return False
        squeeze = lambda s: re.sub(r'\s+', '', s or '')
        want = squeeze(text)
        got = squeeze(seen)
        return bool(want) and want[:24] in got

    def _wait_stable(self, timeout=9.0, interval=1.5):
        """等编辑页连续两帧完全一致（缩略图/动画加载完）再动手。

        不等就会出现"点了 Post 之后画面变了"的假成功：变的其实是自己的缩略图
        还在加载（2026-10-16 实录）。
        """
        previous = self._shot()
        waited = 0.0
        while waited < timeout:
            time.sleep(interval)
            waited += interval
            current = self._shot()
            if current.tobytes() == previous.tobytes():
                return current
            previous = current
        return previous

    def editor_visible(self, image):
        """编辑页是否还在：Post 按钮位置仍然是微信绿。

        判"发表成功"必须看编辑页有没有真的退出，而不是"画面有没有变化"。
        实测点了 Post（坐标还差 6px 没点中）之后缩略图加载完成造成画面变化，
        草稿页仍在，却被记成 PUBLISHED —— 这是最危险的一类假成功。
        """
        x, y = self.coords['publish_button']
        box = image.crop((max(0, x - 55), max(0, y - 16),
                          min(image.width, x + 55), min(image.height, y + 20)))
        import numpy as np
        px = np.asarray(box.convert('RGB'), dtype='int16')
        green = ((px[:, :, 0] < 140) & (px[:, :, 1] > 150) & (px[:, :, 2] < 160))
        return bool(green.mean() >= 0.25)

    def publish_now(self, text, image_path=None, before_post=None):
        """完整发布（含点 Post）。仅在人工批准后调用。"""
        self._need('publish_button')
        self.publish(text, image_path)
        before = self._wait_stable()      # 等缩略图加载完，避免假阳性
        if before_post is not None:
            before_post()
        self._click('publish_button')
        closed = False
        after = None
        for _ in range(6):
            time.sleep(1.5)
            after = self._shot()
            err = self.post_error(after)
            if err:
                raise PublisherError('发表失败：界面报了图片/内容没发出去（%s），不重试' % err)
            if not self.editor_visible(after):
                closed = True
                break
        if not closed:
            raise PublisherError('点了 Post 之后编辑页仍在（没发出去），结果不确定；不重试')
        # 编辑页收起 ≠ 真的发出去了：图片是异步上传的，失败红条会晚几秒才弹
        # （实测 2026-10-16：点完 Post 编辑页立刻收起，几秒后才报 Photos not sent.）
        for _ in range(6):
            time.sleep(1.5)
            after = self._shot()
            err = self.post_error(after)
            if err:
                raise PublisherError('发表失败：图片/内容没发出去（%s），不重试' % err)
        return after

    POST_ERROR_BOX = (180, 320, 400, 450)   # 窗口相对：失败红条常驻位置

    def post_error(self, image=None):
        """点完 Post 后界面有没有报"没发出去"。

        只看"编辑页消失了"不够：图片上传失败时微信也会立刻收起编辑页，
        几秒后才弹红条（实测 "Photos not sent."），结果被记成 PUBLISHED。
        红条是覆盖层，既不在朋友圈窗口截图里、文字又是小号白字（整窗 OCR
        只有乱码），但每条红条左侧的红色圆图标很好认——直接数红像素。
        """
        try:
            x, y = self._win_origin()
            root = Image.open(io.BytesIO(
                self._sh(['import', '-window', 'root', 'png:-'], timeout=40))).convert('RGB')
        except Exception:
            return ''
        x1, y1, x2, y2 = self.POST_ERROR_BOX
        crop = root.crop((max(0, x + x1), max(0, y + y1),
                          min(root.width, x + x2), min(root.height, y + y2)))
        import numpy as np
        px = np.asarray(crop, dtype='int16')
        r, g, b = px[:, :, 0], px[:, :, 1], px[:, :, 2]
        red = int(((r > 150) & (r - g > 60) & (r - b > 60)).sum())
        return ('error-banner(%d px)' % red) if red >= 120 else ''

    def _wait_window_gone(self, pattern, timeout):
        for _ in range(timeout):
            if not self._window_ids(pattern):
                return True
            time.sleep(1.0)
        return False

    def _dialog_type_path(self, dialog_wid, path):
        """Qt 文件对话框：--window 直送点击 File name → ctrl+a → 键入完整路径。"""
        self._need('file_path_input')
        fx, fy = self.coords['file_path_input']
        info = self._sh(['xdotool', 'getwindowgeometry', dialog_wid]).decode('utf-8', 'ignore')
        pos = [l for l in info.splitlines() if 'Position' in l][0]
        wx, wy = (int(v) for v in pos.split(':')[1].split('(')[0].strip().split(','))
        lx, ly = fx - wx, fy - wy
        self._sh(['xdotool', 'mousemove', '--window', dialog_wid, str(lx), str(ly)])
        time.sleep(0.2)
        self._sh(['xdotool', 'click', '--window', dialog_wid, '1'])
        time.sleep(0.4)
        self._sh(['xdotool', 'key', '--window', dialog_wid, '--clearmodifiers', 'ctrl+a'])
        time.sleep(0.2)
        self._sh(['xdotool', 'type', '--window', dialog_wid, '--clearmodifiers', path])
        time.sleep(0.8)

    # ---------- 互动（赞评） ----------
    def _interact_coords(self):
        """互动专用坐标（窗口相对，存 config/moments-coords.json 的 interact_ui）。"""
        iu = self.coords.get('interact_ui') or {}
        if not iu:
            raise NotImplementedError(
                '互动坐标未标定：config/moments-coords.json 缺 interact_ui'
                '（先按 README「互动链路」标定）')
        return iu

    def _win_origin(self, wid=None):
        """Moments 窗口实时原点（窗口可能被移动，坐标每次现算）。"""
        wid = wid or self.moments_wid or self.find_moments_window()
        if not wid:
            raise PublisherError('Moments 窗口未找到（朋友圈面板没打开）')
        info = self._sh(['xdotool', 'getwindowgeometry', '--shell', wid]).decode(
            'utf-8', 'ignore')
        mx = re.search(r'X=(-?\d+)', info)
        my = re.search(r'Y=(-?\d+)', info)
        if not (mx and my):
            raise PublisherError('读不到 Moments 窗口原点')
        return int(mx.group(1)), int(my.group(1))

    def _click_rel(self, rx, ry):
        """窗口相对坐标点击（互动专用；发布链路用绝对坐标 _click）。"""
        ox, oy = self._win_origin()
        self._sh(['xdotool', 'mousemove', str(ox + rx), str(oy + ry)])
        time.sleep(0.2)
        self._sh(['xdotool', 'click', '1'])
        time.sleep(0.6)

    @staticmethod
    def find_more_buttons(image, x1=515, x2=547, y_from=60):
        """像素扫描定位信息流里各动态卡片的 ··· 按钮。

        按钮特征（2026-10-16 实测）：32x20 圆角块，底色 (247,247,247)，
        内有两个 (105,123,160) 左右的点。返回窗口相对 [(x, y)]，按 y 升序
        （信息流从上往下）。检测不到返回 []。
        """
        px = image.load()
        rows = []
        for y in range(y_from, image.height - 12):
            bg = dot = 0
            for yy in range(max(0, y - 9), min(image.height, y + 10)):
                for xx in range(x1, x2):
                    r, g, b = px[xx, yy]
                    if (r, g, b) == (247, 247, 247):
                        bg += 1
                    elif 60 < r < 140 and 80 < g < 150 and 120 < b < 190:
                        dot += 1
            if bg >= 250 and dot >= 4:
                rows.append(y)
        clusters = []
        for y in rows:
            if clusters and y - clusters[-1][-1] <= 3:
                clusters[-1].append(y)
            else:
                clusters.append([y])
        return [((x1 + x2) // 2, sum(c) // len(c)) for c in clusters]

    def card_author(self, image, btn_y, ocr):
        """OCR 按钮上方的卡片区，取第一行当作者名（核专用，防点错卡片）。"""
        strip = image.crop((95, max(0, btn_y - 460), image.width, btn_y - 8))
        try:
            text = ocr(strip, 6)
        except Exception:
            return ''
        for line in [l.strip() for l in str(text).splitlines() if l.strip()]:
            return line[:30]
        return ''

    def _scroll_feed(self, image, direction, point=None):
        """滚轮必须落在当前窗口内部；每次重读原点，拒绝越界而非猜测。"""
        w, h = image.size
        x, y = point if point is not None else (w // 2, h * 3 // 4)
        if (direction not in (4, 5) or not isinstance(x, int) or not isinstance(y, int)
                or not (20 <= x < w - 20 and 60 <= y < h - 20)):
            raise PublisherError('朋友圈滚动坐标越界或窗口尺寸异常，拒绝滚动')
        ox, oy = self._win_origin()
        self._sh(['xdotool', 'mousemove', str(ox + x), str(oy + y)])
        time.sleep(0.2)
        self._sh(['xdotool', 'click', str(direction)])
        time.sleep(1.0)

    def scroll_feed_to_top(self, feed_cx=None, feed_cy=None, max_scrolls=10):
        """信息流滚到顶：反复上滚直到两张截图一致（稳定即到顶）。"""
        prev = None
        for _ in range(max_scrolls):
            shot = self._shot()
            if prev is not None and shot.tobytes() == prev.tobytes():
                return
            prev = shot
            point = (feed_cx if feed_cx is not None else shot.width // 2,
                     feed_cy if feed_cy is not None else shot.height * 3 // 4)
            self._scroll_feed(shot, 4, point)
        # 滚满次数仍不稳定也返回（调用方靠 OCR 核验兜底）

    def focus_moment(self, author, ocr=None, max_cards=10, target_text=None):
        """仅接受完整作者+完整正文；多卡片边界不可靠时拒绝，不猜坐标。"""
        iu = self._interact_coords()
        target = normalize(author)
        body = normalize(target_text)
        if not target or len(body) < 8 or any(mark in body for mark in ('…', '...', '[图片]', '[表情]')):
            raise PublisherError('需要完整作者及至少8字的明确正文；纯图片/截断正文不可互动')
        x1 = iu.get('more_scan_x1', 515)
        x2 = iu.get('more_scan_x2', 547)
        ocr = ocr or self.ui.ocr
        self.scroll_feed_to_top()
        for _ in range(max_cards):
            shot = self._shot()
            buttons = self.find_more_buttons(shot, x1, x2)
            if not buttons:
                break
            if len(buttons) != 1:
                raise PublisherError('多卡片边界有歧义，拒绝按作者猜测目标')
            bx, by = buttons[0]
            strip = shot.crop((95, max(0, by - 460), shot.width, by - 8))
            lines = [l.strip() for l in str(ocr(strip, 6)).splitlines() if l.strip()]
            if len(lines) >= 2 and normalize(lines[0]) == target and normalize(''.join(lines[1:])) == body:
                # 识别与点击之间界面不能变化；保守比较整窗，时间刷新也会拒绝。
                confirmed = self._shot()
                if confirmed.size != shot.size or confirmed.tobytes() != shot.tobytes():
                    raise PublisherError('核验后信息流发生变化，拒绝点击')
                return (bx, by)
            self._scroll_feed(shot, 5)
        raise PublisherError('未找到作者和完整正文同时精确匹配的动态，不互动')

    def _find_menu_window(self, timeout=6):
        """点 ··· 后弹窗是独立小窗口（实测 274x38，标题 wechat）。
        按尺寸找，返回 (wid, (origin_x, origin_y))；找不到返回 (None, None)。"""
        iu = self._interact_coords()
        mw, mh = iu.get('menu_size', [274, 38])
        for _ in range(timeout * 2):
            for wid in self._window_ids('wechat'):
                try:
                    info = self._sh(['xdotool', 'getwindowgeometry', '--shell',
                                     wid]).decode('utf-8', 'ignore')
                    w = re.search(r'WIDTH=(\d+)', info)
                    h = re.search(r'HEIGHT=(\d+)', info)
                    x = re.search(r'X=(-?\d+)', info)
                    y = re.search(r'Y=(-?\d+)', info)
                    if not (w and h and x and y):
                        continue
                    if abs(int(w.group(1)) - mw) <= 8 and \
                            abs(int(h.group(1)) - mh) <= 8:
                        return wid, (int(x.group(1)), int(y.group(1)))
                except Exception:
                    continue
            time.sleep(0.5)
        return None, None

    def like_and_comment(self, author, comment_text, like=True, comment=True, before_action=None, target_text=None):
        """对指定作者的动态：定位卡片→点···→（可选）赞→（可选）评论→发送。

        铁律（与发布一致）：
        - 每步截图验证，界面没按预期变就抛 PublisherError，不重试不瞎点；
        - 评论文案进方法前后各过一次安全闸（sanitize_for_moment）；
        - 发送前确认输入框里确实有字（粘贴前后截图比对）；
        - like=False 时绝不点 Like；comment=False 时绝不打开评论框。
        """
        iu = self._interact_coords()
        if comment:
            for k in ('comment_input', 'comment_send', 'menu_comment_offset'):
                if not iu.get(k):
                    raise NotImplementedError('互动坐标未标定: %s' % k)
        if like and not iu.get('menu_like_offset'):
            raise NotImplementedError('互动坐标未标定: menu_like_offset')
        safe_comment = sanitize_for_moment(comment_text, 60) if comment else ''

        check = before_action or (lambda: None)
        check()
        bx, by = self.focus_moment(author, target_text=target_text)
        check()
        self._click_rel(bx, by)
        time.sleep(0.8)
        wid, origin = self._find_menu_window()
        if not wid:
            raise PublisherError('点了 ··· 但弹窗菜单没出现（274x38 小窗口）')

        if like:
            lx, ly = iu['menu_like_offset']
            self._sh(['xdotool', 'mousemove', str(origin[0] + lx),
                      str(origin[1] + ly)])
            time.sleep(0.2)
            check()
            self._sh(['xdotool', 'click', '1'])
            time.sleep(1.0)

        if comment:
            cx, cy = iu['menu_comment_offset']
            self._sh(['xdotool', 'mousemove', str(origin[0] + cx),
                      str(origin[1] + cy)])
            time.sleep(0.2)
            check()
            self._sh(['xdotool', 'click', '1'])
            time.sleep(1.2)
            ix, iy = iu['comment_input']
            self._click_rel(ix, iy)
            time.sleep(0.3)
            before = self._shot()
            check()
            self.ui.clipboard_write(safe_comment)
            self._key('ctrl+v')
            time.sleep(0.8)
            after = self._shot()
            if after.tobytes() == before.tobytes():
                raise PublisherError('粘贴评论后输入框无变化，结果不确定；不发送')
            sx, sy = iu['comment_send']
            check()
            self._click_rel(sx, sy)
            for _ in range(4):
                time.sleep(1.2)
                sent = self._shot()
                if sent.tobytes() != after.tobytes():
                    return {'author': author, 'liked': bool(like),
                            'commented': safe_comment, 'sent': True}
            raise PublisherError('点发送后界面无变化，结果不确定；不重试')
        return {'author': author, 'liked': bool(like), 'commented': '',
                'sent': False}
