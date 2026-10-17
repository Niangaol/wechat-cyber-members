"""仅操作 WSL X11 微信；不注入、不读聊天数据库、不操作 Windows 客户端。"""
import io, os, re, subprocess, time, hashlib
from pathlib import Path
from difflib import SequenceMatcher
from PIL import Image
from screen import list_x_windows
from chat_anchors import title_anchor_matches
from output_safe import check_output

class SafetyError(RuntimeError): pass

class UIUnavailable(SafetyError):
    """UI 现在不可用（窗口没起来/还停在登录窗/归位不了）。

    和"发错窗"这种策略性失败分开：环境不可用是一过性的，消息该在队列里等，
    不该吃掉重试次数（重启微信客户端时最容易撞上）。
    """

def normalize(text):
    return re.sub(r'\s+', '', text or '')

# 标题栏小字上的 OCR 混淆族：I / l / 1 / | 几乎分不出来。实测把
# "Vibe AI Lab 招新交流群" 读成 "Vibe Al Lab 招新交流群"，严格比较会一直切换失败。
# 只折叠这一族，而且**整个标题**仍必须一致，所以不会把别的会话认成目标。
_OCR_FOLD = str.maketrans({'I': 'l', 'i': 'l', '1': 'l', '|': 'l'})


def _fold_ocr(text):
    return normalize(text).translate(_OCR_FOLD)


def title_matches(expected, actual, is_group=False):
    """授权检查只接受完整标题（折叠 OCR 混淆后）；群聊额外接受末尾人数，绝不接受子串。"""
    expected, actual = normalize(expected), normalize(actual)
    if not expected or not actual:
        return False
    if is_group:
        # 人数后缀单独剥掉再比：里面的数字不能被折叠成 l
        stripped = re.fullmatch(r'(?P<head>.*?)[（(][0-9]+[）)]', actual)
        if stripped:
            actual = stripped.group('head')
    if expected == actual:
        return True
    return _fold_ocr(expected) == _fold_ocr(actual)

def chat_left(image):
    """识别可拖动的会话列表分隔线，失败时维持既有布局。"""
    import numpy as np
    a = np.asarray(image.convert("RGB"))
    left = 283 if image.width == 1021 else 273
    for x in range(250,min(430,image.width//2)):
        col = a[90:image.height-190,x]
        if len(col) and (col.max(0)-col.min(0)).max()<3 and 195<=col.mean()<=225:
            left = x
    return left


# 图片发送：输入区区域（避开左侧会话列表、工具栏图标和 Send 按钮）。
# 2026-10-17 实测：空输入框前景像素 40–70（绿色文本光标）；粘贴图片预览后 ≈5000 px。
COMPOSER = (345, 632, 890, 680)


def composer_foreground(image):
    """输入区里与底色差异明显的像素数。"""
    import numpy as np
    a = np.asarray(image.crop(COMPOSER).convert('RGB'), dtype=np.int16)
    bg = np.median(a.reshape(-1, 3), axis=0)
    return int((np.max(np.abs(a - bg), axis=2) > 24).sum())


def composer_empty(image):
    """输入区是否为空：浅灰底 + 前景像素很少（只允许文本光标/抗锯齿）。

    阈值 300：空输入框实测 40–70 px（光标），粘贴图片预览实证 5337 px；
    以前用 64 会把光标误判成"已有内容"，导致发图链路永远拒绝发送。
    """
    import numpy as np
    a = np.asarray(image.crop(COMPOSER).convert('RGB'), dtype=np.int16)
    bg = np.median(a.reshape(-1, 3), axis=0)
    if not bool(np.all((bg >= 225) & (bg <= 248))):
        return False           # 整块黑/白图片被粘贴时底色会变
    return composer_foreground(image) <= 300


def composer_stable(a, b, tolerance=260):
    """两次截图之间输入区是否没变：容忍文本光标闪烁/抗锯齿（实测光标约 40–120 px）。"""
    import numpy as np
    x = np.asarray(a.crop(COMPOSER).convert('RGB'), dtype=np.int16)
    y = np.asarray(b.crop(COMPOSER).convert('RGB'), dtype=np.int16)
    return int((np.max(np.abs(x - y), axis=2) > 24).sum()) <= tolerance


def composer_changed(before, after):
    """输入区是否出现了足够明确的新内容（新粘贴的图片预览）。"""
    import numpy as np
    a = np.asarray(before.crop(COMPOSER).convert('RGB'), dtype=np.int16)
    b = np.asarray(after.crop(COMPOSER).convert('RGB'), dtype=np.int16)
    mask = np.max(np.abs(a - b), axis=2) > 24
    ys, xs = np.where(mask)
    return bool(len(xs) >= 256 and xs.max() - xs.min() >= 12 and ys.max() - ys.min() >= 10)


MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000


def prepare_png_bytes(data):
    """把任意静态 PNG/JPEG/WebP 冻结成白底 PNG：去元数据、最长边 2048、限制大小。

    发图流程和生图链路共用这一个规范化入口，保证"发出去的字节"可复现、可核验。
    """
    import io as _io
    from PIL import Image, ImageOps
    if len(data) > MAX_IMAGE_BYTES:
        raise SafetyError('图片超过 20MB')
    with Image.open(_io.BytesIO(data)) as im:
        if (im.format not in ('PNG', 'JPEG', 'WEBP')
                or getattr(im, 'n_frames', 1) != 1
                or im.width * im.height > MAX_IMAGE_PIXELS):
            raise SafetyError('只支持不超过1600万像素的静态 PNG/JPEG/WebP')
        im.load()
        frame = ImageOps.exif_transpose(im).convert('RGBA')
        # 白底避免透明像素在微信里变黑；复制像素以丢弃 EXIF/注释等元数据。
        canvas = Image.new('RGB', frame.size, 'white')
        canvas.paste(frame, mask=frame.getchannel('A'))
        canvas.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
        out = _io.BytesIO()
        canvas.save(out, format='PNG')
        png = out.getvalue()
        size = canvas.size
    if len(png) > MAX_IMAGE_BYTES:
        raise SafetyError('转换后的 PNG 超过20MB')
    return png, size[0], size[1]


class WeChatUI:
    def __init__(self, cfg):
        self.cfg = cfg
        self.env = dict(os.environ, DISPLAY=cfg['display'])
        self.wid = None

    def run(self, args, data=None, timeout=12):
        """X 命令失败/超时一律 fail-closed 成 SafetyError。

        直接把 CalledProcessError/TimeoutExpired 抛给主循环会被当成“未知异常”计入
        STOP 阈值——WSL/微信正在启动或正在关机时 xdotool 必然超时，结果每次开机
        都把常驻机器人自己按停。UI 不可用本来就发不出去，所以这里降级为
        SafetyError：不发、不计失败、也不会盲重试。
        """
        name = args[0] if args else '?'
        try:
            return subprocess.run(args, input=data, capture_output=True,
                                  env=self.env, timeout=timeout, check=True).stdout
        except subprocess.TimeoutExpired:
            raise UIUnavailable('UI 命令超时：%s（禁止发送）' % name)
        except subprocess.CalledProcessError as e:
            raise UIUnavailable('UI 命令失败 rc=%s：%s（禁止发送）' % (e.returncode, name))

    def _repair_window(self, wid):
        """把主窗口恢复到配置的固定位置和尺寸（xdotool 由内核等待完成）。"""
        size = (str(self.cfg['expected_width']), str(self.cfg['expected_height']))
        ox, oy = (self.cfg.get('window_origin') or [0, 0])[:2]
        self.run(['xdotool', 'windowsize', '--sync', wid, size[0], size[1]])
        self.run(['xdotool', 'windowmove', wid, str(ox), str(oy)])

    @staticmethod
    def _weixin_windows(cfg):
        return [w for w in list_x_windows(cfg['display'])
                if w['title'] == 'Weixin' and '"wechat" "wechat"' == w['classes']]

    # 登录窗和主窗同名同类，只能靠尺寸区分（登录窗实测 292x396）
    MIN_MAIN_WIDTH = 600
    MIN_MAIN_HEIGHT = 600

    def capture(self):
        wins = self._weixin_windows(self.cfg)
        if len(wins) != 1:
            raise UIUnavailable('主窗口不唯一或未登录；禁止发送')
        if (wins[0]['w'] < self.MIN_MAIN_WIDTH
                or wins[0]['h'] < self.MIN_MAIN_HEIGHT):
            # 这是登录窗：绝不能把它 resize 成主窗尺寸（会把登录界面拉变形，
            # 用户就没法扫码了），直接当作"未登录"拒绝。
            raise UIUnavailable('微信处于登录/未登录小窗（%dx%d），禁止操作'
                              % (wins[0]['w'], wins[0]['h']))
        expected = (self.cfg['expected_width'], self.cfg['expected_height'])
        origin = tuple((self.cfg.get('window_origin') or [0, 0])[:2])
        if ((wins[0]['w'], wins[0]['h']) != expected
                or (wins[0].get('abs_x'), wins[0].get('abs_y')) != origin):
            # 每次操作前把窗口归位到固定几何；恢复不了才拒绝（确定性要求）。
            self._repair_window(wins[0]['id'])
            wins = self._weixin_windows(self.cfg)
            if len(wins) != 1:
                raise UIUnavailable('窗口归位后主窗口不唯一；禁止发送')
            if (wins[0]['w'], wins[0]['h']) != expected:
                raise UIUnavailable('窗口尺寸无法恢复到 %dx%d；禁止发送' % expected)
        self.wid = wins[0]['id']
        self.last_abs = (wins[0]['abs_x'], wins[0]['abs_y'])
        data = self.run(['import', '-window', self.wid, 'png:-'])
        return Image.open(io.BytesIO(data)).convert('RGB')

    def activate(self):
        """把微信主窗拉回前台、顺手 Esc 掉可能挡着的浮层（观察连续失败时自救）。

        实测会挡路的：小程序窗、朋友圈浮层、失焦的旧对话框——它们一挡，
        每个会话都切不进去，主循环会一直 poll_degraded 自己好不了。
        Escape 只关浮层，不会清掉输入框里的草稿（实测单按 Escape 无效）。
        """
        wins = self._weixin_windows(self.cfg)
        if len(wins) != 1:
            raise UIUnavailable('主窗口不唯一，拒绝自救操作')
        if (wins[0]['w'] < self.MIN_MAIN_WIDTH or wins[0]['h'] < self.MIN_MAIN_HEIGHT):
            raise UIUnavailable('微信处于登录小窗，拒绝自救操作')
        self._repair_window(wins[0]['id'])
        self.run(['xdotool', 'windowactivate', '--sync', str(wins[0]['id'])])
        time.sleep(0.4)
        self.key('Escape')
        time.sleep(0.3)
        return self.capture()

    def ocr(self, image, psm=6):
        image = image.convert('RGB').resize((image.width*3, image.height*3))
        out = io.BytesIO(); image.save(out, 'PNG')
        return self.run(['tesseract','stdin','stdout','-l','chi_sim+eng','--psm',str(psm)],
                        out.getvalue(), timeout=20).decode('utf-8').strip()

    def title_texts(self, image):
        """中文标题的零模型精确匹配备选，不做相似度放行。"""
        left = chat_left(image)
        results = []
        full = image.crop((left+12,28,image.width-80,57)).convert("L")
        ink = full.point(lambda p:255 if p<140 else 0).getbbox()
        for width in (200, 300):
            # 有文字跨出裁剪右缘时不能接受截断前缀作为完整标题。
            if ink is None or ink[2] > width:
                continue
            crop = image.crop((left+12, 28, min(left+12+width,image.width-80), 57)).convert("L")
            if crop.point(lambda p:255 if p<140 else 0).getbbox() is None:
                continue
            out = io.BytesIO()
            crop.resize((crop.width*2,crop.height*2)).point(lambda p:0 if p<150 else 255).save(out,"PNG")
            text = self.run(["tesseract","stdin","stdout","-l","chi_sim","--psm","7"],
                            out.getvalue(), timeout=20).decode("utf-8").strip()
            results.append(normalize(text))
        return results

    def _draft_text(self, image):
        """草稿检测只看工具栏下方的文字区。

        旧区域(283,605,945,654)盖住工具栏图标，tesseract 会把图标读成
        「DTVYCIOw&YWw」之类的乱码，造成空输入框被误判为有草稿（2026-10-16 实测）。
        文字区避开右侧 Send 按钮（含「Send(S)」文字），从左缘起即可判定有无内容。
        """
        return normalize(self.ocr(image.crop((chat_left(image), 632, 890, 735)), 6))

    def verify_target(self, image=None, expected_chat=None):
        image = image if image is not None else self.capture()
        title = normalize(self.ocr(image.crop((283, 20, 700, 61)), 7))
        # 本机OCR会把年糕识别成"年料"；仅用人工核验过的标题像素模板兜底，绝不模糊放行其他人名。
        anchor = Path(__file__).resolve().parent.parent / 'config' / 'target-title.png'
        expected = self.cfg.get('target_chat', '') if expected_chat is None else expected_chat
        pixel_match = False
        if normalize(expected) and normalize(expected) == normalize(self.cfg.get('target_chat', '')) and anchor.exists():
            with Image.open(anchor) as template:
                pixel_match = template.convert('RGB').tobytes() == image.crop((283,20,700,61)).convert('RGB').tobytes()
        is_group = normalize(expected) in {normalize(g) for g in self.cfg.get('group_whitelist', [])}
        if (not title_matches(expected, title, is_group) and not pixel_match
                and not title_anchor_matches(expected, image)
                and not any(title_matches(expected, t, is_group) for t in self.title_texts(image))):
            raise SafetyError('会话标题未精确匹配白名单；禁止发送')
        return image

    def clipboard_read(self):
        return self.run(['xsel','--clipboard','--output'], timeout=5).decode('utf-8')

    def clipboard_write(self, text):
        self.run(['xsel','--clipboard','--input'], text.encode('utf-8'), timeout=5)

    # ---------- 图片发送（与 resident 共用同一套已核验流程） ----------
    def clip_read(self):
        """备份剪贴板；没有任何进程持有剪贴板时返回 ('none', b'')（无需恢复）。"""
        try:
            targets = self.run(['xclip', '-selection', 'clipboard', '-out', '-target', 'TARGETS'])
        except UIUnavailable:
            return 'none', b''
        available = targets.decode('utf-8', 'ignore').splitlines()
        for fmt in ('image/png', 'UTF8_STRING', 'STRING'):
            if fmt in available:
                data = self.run(['xclip', '-selection', 'clipboard', '-out', '-target', fmt])
                return fmt, data
        raise SafetyError('无法保存当前剪贴板格式，拒绝覆盖')

    def clip_write(self, fmt, data):
        if fmt == 'none':
            return
        # xclip fork 后持有选择区，DEVNULL 防止后台选择区进程占住输出管道。
        p = subprocess.Popen(['xclip', '-selection', 'clipboard', '-in', '-target', fmt],
                             stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, env=self.env)
        try:
            p.communicate(data, timeout=5)
        except BaseException:
            p.kill(); p.wait()
            raise
        if p.returncode:
            raise SafetyError('写入剪贴板失败')

    def send_image_png(self, data, expected_chat=None, mark_submitting=None, guard=None):
        """发一张 PNG：标题核验 → 输入区必须为空 → 粘贴 → 预览像素核验 → Return → 复查清空。

        每次关键操作前都重新核验标题；不自动清任何草稿；发送后输入区没清空就
        按"结果不确定"报错，绝不重按发送键。
        """
        if guard: guard()
        before = self.verify_target(expected_chat=expected_chat)
        if self._draft_text(before) or not composer_empty(before):
            raise SafetyError('输入区已有文字或图片，保留现场并拒绝发送')
        original = self.clip_read()
        try:
            if guard: guard()
            self.clip_write('image/png', data)
            actual = self.run(['xclip', '-selection', 'clipboard', '-out', '-target', 'image/png'])
            if actual != data:
                raise SafetyError('剪贴板内容与要发送的图片不符')
            if guard: guard()
            self.verify_target(expected_chat=expected_chat)
            self.focus_window()                 # 不激活窗口时粘贴会静默失败
            ax, ay = getattr(self, 'last_abs', (0, 0))
            self.run(['xdotool', 'mousemove', str(ax + 570), str(ay + 660)])
            self.run(['xdotool', 'click', '1'])
            self.key('ctrl+v')
            time.sleep(1.5)
            if guard: guard()
            preview = self.verify_target(expected_chat=expected_chat)
            if not composer_changed(before, preview):
                raise SafetyError('输入区未出现新的图片预览；未按发送键')
            if guard: guard()
            ready = self.verify_target(expected_chat=expected_chat)
            if not composer_stable(preview, ready):
                raise SafetyError('预览在发送前发生变化；未按发送键')
            if mark_submitting:
                mark_submitting()      # 先持久化"可能已发送"，再按 Return
            if guard: guard()
            last = self.verify_target(expected_chat=expected_chat)
            if not composer_stable(ready, last):
                raise SafetyError('最终发送前预览变化，拒绝按发送键')
            self.key('Return')
            time.sleep(1.5)
            if guard: guard()
            final = self.verify_target(expected_chat=expected_chat)
            if self._draft_text(final) or not composer_empty(final):
                raise SafetyError('发送后输入区未清空；结果不确定，禁止重试')
            return {'status': 'SUBMITTED', 'delivery_confirmed': False}
        finally:
            try:
                self.clip_write(*original)
            except Exception:          # noqa: BLE001 恢复失败不能掩盖真实结果
                pass

    def open_chat_tab(self):
        """把左侧导航切回「聊天」页：好友发现流程可能把界面留在通讯录。

        只点左侧第一个导航图标，不碰会话列表、不碰输入框、不影响任何草稿。
        """
        if not self.wid: raise SafetyError('没有已核验的窗口')
        ax, ay = getattr(self, 'last_abs', (0, 0))
        self.run(['xdotool', 'mousemove', str(ax + 32), str(ay + 104)])
        self.run(['xdotool', 'click', '1'])
        time.sleep(0.5)

    def focus_window(self):
        """把微信窗口激活到前台：实测不先激活窗口，点输入区后粘贴会静默失败
        （Weston 下点击不会自动聚焦窗口，输入框拿不到键盘焦点）。"""
        if not self.wid: raise SafetyError('没有已核验的窗口')
        self.run(['xdotool', 'windowfocus', self.wid])

    def key(self, key):
        if not self.wid: raise SafetyError('没有已核验的窗口')
        # 主窗口是 Qt 应用：--window 的 XSendEvent 按键会被它忽略（实测 ctrl+v 无效果），
        # 必须走 XTEST 全局键盘；先用 XSetInputFocus 把焦点钉在微信窗口上。
        self.run(['xdotool', 'windowfocus', self.wid])
        self.run(['xdotool', 'key', '--clearmodifiers', key])

    def chat_image(self, image):
        sidebar = chat_left(image)
        return image.crop((sidebar, 72, image.width-3, image.height-156))

    def send_image(self, path, caption=''):
        """兼容旧调用：读文件 → 规范化 PNG → 走已验证的 send_image_png。可选 caption 先发文字。"""
        # 旧实现的预览区 (283,540,945,605) 在 2026-10-17 的客户端版本上已不成立：
        # 图片预览实际出现在输入框内。这里统一交给已验证的 send_image_png，不再自己判断。
        png, _, _ = prepare_png_bytes(Path(path).read_bytes())
        if caption:
            self.send_text(str(caption)[:self.cfg.get('reply_max_chars', 200)])
        return self.send_image_png(png)

    def send_sticker(self, sticker_coords):
        """发表情包：点输入框旁表情图标→面板出现→点击目标表情→发送。
        sticker_coords={'panel_icon':(x,y),'sticker':(x,y)}；未标定拒绝执行。"""
        if not sticker_coords or not sticker_coords.get('panel_icon') or not sticker_coords.get('sticker'):
            raise SafetyError('表情面板坐标未标定，拒绝执行')
        image = self.verify_target()
        if self._draft_text(image):
            raise SafetyError('输入框有草稿，保留现场并拒绝覆盖')
        px, py = sticker_coords['panel_icon']
        self.run(['xdotool', 'mousemove', str(px), str(py)])
        time.sleep(0.3)
        self.run(['xdotool', 'click', '1'])
        time.sleep(1.5)  # 等表情面板弹出
        sx, sy = sticker_coords['sticker']
        self.run(['xdotool', 'mousemove', str(sx), str(sy)])
        time.sleep(0.3)
        self.run(['xdotool', 'click', '1'])
        time.sleep(1.0)
        after = self.verify_target()
        if after.tobytes() == image.tobytes():
            raise SafetyError('点击表情后界面无变化，结果不确定；不重试')
        return after

    def input_text(self, expected_chat=None):
        """读输入框里现在有什么（草稿判断/清理自证用）。读不到返回 ''。"""
        try:
            self.verify_target(expected_chat=expected_chat)
            ax, ay = getattr(self, 'last_abs', (0, 0))
            self.run(['xdotool', 'mousemove', str(ax + 500), str(ay + 700)])
            time.sleep(0.2)
            self.run(['xdotool', 'click', '1'])
            time.sleep(0.3)
            self.clipboard_write('__WECHAT_INPUT_PROBE__')
            self.key('ctrl+a'); self.key('ctrl+c')
            time.sleep(0.25)
            got = self.clipboard_read() or ''
            # 输入框空的时候 ctrl+c 复制不到东西，剪贴板里还是我们写的探针：
            # 那是"空"，不是"还有内容"（否则清理后永远自证失败）
            return '' if got.strip() == '__WECHAT_INPUT_PROBE__' else got
        except Exception:      # noqa: BLE001 读不到就当空
            return ''

    def clear_input(self, expected_chat=None, expect_text=None):
        """清空输入框——只用于清理"我们自己刚打进去、没发出去"的草稿。

        草稿留在输入框里，这条会话之后每次发送都会被"输入框有草稿"挡掉，
        等于永久哑掉（2026-10-17 实测：群里一张图之后，后面几条回复全被拒）。
        判据用"读出来的内容"而不是 _draft_text：实测同一份草稿在 _draft_text
        眼里一会儿有一会儿没有。传了 expect_text 就只删内容完全一致的那份。
        """
        now = self.input_text(expected_chat=expected_chat)
        if not now.strip():
            return False
        if expect_text is not None and now.strip() != str(expect_text).strip():
            raise SafetyError('输入框里不是我们刚写的那句，拒绝清理')
        image = self.verify_target(expected_chat=expected_chat)
        if not self._draft_text(image):
            # 内容非空但草稿检测看不出来：按内容来，继续清
            pass
        ax, ay = getattr(self, 'last_abs', (0, 0))
        self.run(['xdotool', 'mousemove', str(ax + 500), str(ay + 700)])
        time.sleep(0.2)
        self.run(['xdotool', 'click', '1'])
        time.sleep(0.3)
        # ctrl+a 全选 + Delete 是这套客户端里唯一可靠的清空方式（实测）
        self.key('ctrl+a')
        self.key('Delete')
        time.sleep(0.4)
        after = self.input_text(expected_chat=expected_chat)
        if after.strip():
            raise SafetyError('草稿清理后输入框仍有内容，拒绝继续；请人工看一眼')
        return True

    def send_text(self, text, expected_guard=None, expected_chat=None):
        text = check_output(text, self.cfg['reply_max_chars'])
        image = self.verify_target(expected_chat=expected_chat)
        if self._draft_text(image):
            raise SafetyError('输入框有草稿，保留现场并拒绝覆盖')
        old = self.clipboard_read()
        try:
            # 先点一下输入区（工具栏下方、Send 按钮左侧），确保键盘焦点在输入框。
            self.focus_window()
            ax, ay = getattr(self, 'last_abs', (0, 0))
            self.run(['xdotool', 'mousemove', str(ax + 500), str(ay + 700)])
            time.sleep(0.1)
            self.run(['xdotool', 'click', '1'])
            time.sleep(0.2)
            self.clipboard_write(text)
            self.key('ctrl+v')
            # 逐字回读既是"粘贴已落到输入框"的证明（省掉一次整窗截图+OCR 标题核验），
            # 也容忍界面偶发慢一帧。最多重读 4 次、每次 0.15s，通常第一次就命中。
            actual = ''
            for _ in range(4):
                time.sleep(0.15)
                self.clipboard_write('__WECHAT_READBACK_SENTINEL__')
                self.key('ctrl+a'); self.key('ctrl+c')
                time.sleep(0.15)
                actual = self.clipboard_read()
                if actual == text:
                    break
            if actual != text:
                raise SafetyError('输入框逐字回读不一致；未发送，保留草稿')
            if expected_guard is not None:
                if not callable(expected_guard) or expected_guard() is False:
                    raise SafetyError('发送前授权检查未通过')
            # 发送前最后一次标题核验；不自动重试 Return，避免重复发送。
            self.verify_target(expected_chat=expected_chat)
            self.key('ctrl+End')
            self.key('Return')
            # 发送后核验：只看输入区是否清空（像素判定，5ms），不再重复标题 OCR。
            # 标题在 Return 前刚核验过，这里再做一次 OCR 只会白白多花 0.4s；
            # 输入区清空 + 发送前标题正确，已经足够证明"这次发出去了"。
            time.sleep(0.35)
            after = self.capture()
            if not composer_empty(after):
                time.sleep(0.4)
                after = self.capture()
            if not composer_empty(after):
                raise SafetyError('发送后仍有草稿；结果不确定，禁止重发')
            return after
        finally:
            self.clipboard_write(old)
