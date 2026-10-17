"""朋友圈草稿的人工确认与发布链路。

铁律（与 publisher 的"绝不瞎点"一致）：
1. 没有有效的人工批准令牌，绝不发布；令牌里的 id 必须与待发布草稿一致；
2. 批准时、发布前各过一次安全闸（模型输出可能在生成后被外部改动）；
3. 坐标未标定 → NotImplementedError，原样抛出，调用方知道要先标定；
4. 只有 publisher 回报"界面确实变了"才算成功，才写 PUBLISHED；
   失败/不确定 → 草稿保持 DRAFT；若已有提交占位则禁止重发，需人工核对；
5. dry_run 模式把整条闸门跑一遍但不碰 UI，用于上线前自证。
"""
import json
import hashlib
import os
import uuid
import time
from pathlib import Path

from moments_safe import sanitize_for_moment
from moments_publisher import MomentsPublisher
from ui_lease import ui_lease, UILeaseBusy

ROOT = Path(__file__).resolve().parent.parent
STATE = Path.home() / '.local' / 'state' / 'wechat-bot'
APPROVE_FILE = 'APPROVE_MOMENT'
COORDS_FILE = ROOT / 'config' / 'moments-coords.json'


class ReleaseError(RuntimeError):
    pass


def load_coords(cfg=None, coords_file=None):
    """坐标来源：config/moments-coords.json（标定脚本写的）+ resident.json 的 moments_ui 覆盖。

    两边都只认非空值；文件读不了时静默跳过（等价于"未标定"）。
    """
    coords = {}
    path = Path(coords_file) if coords_file else COORDS_FILE
    if path.exists():
        try:
            coords = {k: v for k, v in json.loads(path.read_text()).items() if v}
        except Exception:
            coords = {}
    for k, v in ((cfg or {}).get('moments_ui') or {}).items():
        if v:
            coords[k] = v
    return coords


class MomentRelease:
    """drafts()/approve()/revoke()/approved_id()/publish()。"""

    def __init__(self, db, ui, composer=None, coords=None, state_dir=None, cfg=None):
        self.db = db
        self.ui = ui
        self.composer = composer
        self.cfg = cfg or {}
        self.state_dir = Path(state_dir) if state_dir else STATE
        self.coords = {k: v for k, v in (coords or {}).items() if v}

    # ---------- 草稿 ----------
    def _row(self, mid):
        return self.db.execute(
            'SELECT id,created,topic,seed,text,image,state FROM moments WHERE id=?',
            (mid,)).fetchone()

    @staticmethod
    def _dict(row):
        if not row:
            return None
        return {'id': row[0], 'created': row[1], 'topic': row[2], 'seed': row[3],
                'text': row[4], 'image': row[5], 'state': row[6]}

    def drafts(self):
        rows = self.db.execute(
            "SELECT id,created,topic,seed,text,image,state FROM moments "
            "WHERE state='DRAFT' ORDER BY created").fetchall()
        return [self._dict(r) for r in rows]

    def draft(self, mid):
        return self._dict(self._row(mid))

    # ---------- 批准令牌 ----------
    @property
    def approve_path(self):
        return self.state_dir / APPROVE_FILE

    def _digest(self, d):
        image_hash = ''
        if d['image']:
            path = Path(d['image'])
            if not path.is_file() or path.stat().st_size > 20 * 1024 * 1024:
                raise ReleaseError('配图缺失或超过20MB，不能批准/发布')
            image_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        content = [d['id'], d['topic'], d['seed'], d['text'], d['image'], image_hash]
        return hashlib.sha256(json.dumps(content, ensure_ascii=False).encode()).hexdigest()

    @property
    def attempt_path(self):
        return self.state_dir / 'PUBLISH_ATTEMPT'

    def approve(self, mid):
        """人工确认某条草稿。令牌落盘（600 权限），可随时 revoke。"""
        d = self.draft(mid)
        if not d or d['state'] != 'DRAFT':
            raise ReleaseError('id=%s 不是待发布草稿' % mid)
        try:
            sanitize_for_moment(d['text'], self.cfg.get('max_chars', 300))
        except ValueError as e:
            raise ReleaseError('草稿未过安全闸，拒绝批准：%s' % e)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.approve_path.with_suffix('.tmp')
        tmp.write_text(json.dumps({'id': int(mid), 'approved_at': time.time(),
                                   'digest': self._digest(d)},
                                  ensure_ascii=False))
        tmp.chmod(0o600)
        tmp.replace(self.approve_path)
        return str(self.approve_path)

    def revoke(self):
        if self.approve_path.exists():
            self.approve_path.unlink()
            return True
        return False

    def approved_id(self):
        """读令牌并校验：格式错/草稿已发布/草稿不存在 → None（视为未批准）。"""
        try:
            data = json.loads(self.approve_path.read_text())
            mid = int(data['id'])
        except Exception:
            return None
        d = self.draft(mid)
        if not d or d['state'] != 'DRAFT':
            return None
        try:
            return mid if data.get('digest') == self._digest(d) else None
        except (OSError, ReleaseError):
            return None

    # ---------- 朋友圈面板 ----------
    def open_moments_panel(self):
        try:
            with ui_lease(self.state_dir):
                return self._open_moments_panel()
        except UILeaseBusy as exc:
            raise ReleaseError(str(exc)) from exc

    def _open_moments_panel(self):
        """点开左侧边栏的朋友圈图标（坐标需标定，未标定不瞎点）。

        面板已经开着就直接返回截图：侧边栏图标是开关，重复点会把面板关掉。
        返回值是主窗口截图，供调用方核验（wsl/moment-release.py 依赖）。
        """
        icon = self.coords.get('moments_icon')
        if not icon:
            raise NotImplementedError('坐标未标定: moments_icon（朋友圈边栏图标）')
        if MomentsPublisher(self.ui, self.coords).find_moments_window():
            return self.ui.capture()
        x, y = icon
        self.ui.run(['xdotool', 'mousemove', str(x), str(y)])
        time.sleep(0.3)
        self.ui.run(['xdotool', 'click', '1'])
        time.sleep(2.0)
        return self.ui.capture()

    # ---------- 发布 ----------
    def _validated(self, mid):
        """批准令牌 + 安全闸 + 配图存在性 + 坐标标定，四道全过才返回待发布内容。"""
        if (self.state_dir / 'STOP').exists():
            raise ReleaseError('STOP 已启用，禁止发布')
        if self.attempt_path.exists():
            raise ReleaseError('存在发布尝试或结果不确定，禁止重发；请人工核对')
        approved = self.approved_id()
        if approved is None:
            raise ReleaseError('没有有效的人工批准令牌（APPROVE_MOMENT 缺失/失效）')
        if mid is not None and int(mid) != approved:
            raise ReleaseError('批准令牌指向 id=%s，与请求的 id=%s 不一致' % (approved, mid))
        d = self.draft(approved)
        if d['image'] and not Path(d['image']).exists():
            raise ReleaseError('配图文件不存在：%s' % d['image'])
        if self.cfg.get('with_image') and not d['image']:
            raise ReleaseError('当前要求图文发布，草稿没有配图')
        text = sanitize_for_moment(d['text'], self.cfg.get('max_chars', 300))
        pub = MomentsPublisher(self.ui, self.coords)
        pub._need('moments_icon', 'camera_icon', 'text_input', 'publish_button')
        return d, text

    def publish(self, moment_id=None, dry_run=False):
        try:
            with ui_lease(self.state_dir):
                return self._publish(moment_id, dry_run)
        except UILeaseBusy as exc:
            raise ReleaseError(str(exc)) from exc

    def _publish(self, moment_id=None, dry_run=False):
        """发布已批准的草稿；dry_run=True 只跑闸门不碰 UI。"""
        d, text = self._validated(moment_id)
        payload = {'id': d['id'], 'topic': d['topic'], 'text': text,
                   'image': d['image'] or ''}
        if dry_run:
            return dict(payload, dry_run=True, approved=True, coords=self.coords)
        if self.composer is None:
            raise ReleaseError('未提供 composer，禁止开始发布')
        pub = MomentsPublisher(self.ui, self.coords)
        attempt_key = uuid.uuid4().hex

        def before_post():
            current, current_text = self._validated(d['id'])
            if current_text != text or current['image'] != d['image']:
                raise ReleaseError('编辑内容发生变化，拒绝提交')
            # 文件级排他占位：提交前 fsync；失败或崩溃不删，不自动重试。
            try:
                fd = os.open(self.attempt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError as e:
                raise ReleaseError('其他发布已占位，禁止重复提交') from e
            with os.fdopen(fd, 'w') as handle:
                json.dump({'id': d['id'], 'attempt_key': attempt_key,
                           'started': time.time()}, handle)
                handle.flush()
                os.fsync(handle.fileno())

        pub.publish_now(text, d['image'] or None, before_post=before_post)
        try:
            attempt = json.loads(self.attempt_path.read_text())
        except (OSError, ValueError):
            raise ReleaseError('没有提交尝试记录，禁止标记发布成功')
        if attempt.get('id') != d['id'] or attempt.get('attempt_key') != attempt_key:
            raise ReleaseError('提交尝试归属不符，禁止标记发布成功')
        self.composer.mark_published(d['id'])
        self.revoke()
        self.attempt_path.unlink()
        return dict(payload, published=time.time())
