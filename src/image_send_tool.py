"""独立人工发图工具；不被 resident 导入，不改自动回复配置或服务。"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time

import numpy as np
from PIL import Image, ImageOps
from chat_navigator import ChatNavigator
from ui_lease import ui_lease, UILeaseBusy
from wechat_ui import (WeChatUI, SafetyError, COMPOSER, composer_empty,
                       composer_changed, composer_foreground, composer_stable,
                       prepare_png_bytes)
# 旧名字保留：发图工具与测试用这两个名字，实现统一在 wechat_ui。
preview_changed = composer_changed
foreground = composer_foreground

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / 'config' / 'resident.json'
STATE = Path.home() / '.local/state/wechat-bot'
MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 16_000_000



class ImageToolError(RuntimeError):
    pass


def load_config(path=CONFIG):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def authorize(cfg, chat):
    """只接受原样登记名字；群白名单优先，私聊同时受开关和黑名单约束。"""
    if not isinstance(chat, str) or not chat.strip():
        raise ImageToolError('必须显式指定会话')
    if chat in cfg.get('group_whitelist', []):
        return 'group:' + chat
    registered = set(cfg.get('direct_whitelist', []))
    registered.add(cfg.get('target_chat', ''))
    if (chat not in registered or not cfg.get('direct_enabled', True)
            or chat in cfg.get('direct_blacklist', [])
            or cfg.get('chat_types', {}).get(chat) == 'group'):
        raise ImageToolError('目标未登记或发送授权已关闭')
    return 'direct:' + chat


def prepare_image(path):
    """仅本地静态图；内容冻结为 PNG（共享规范化实现），不改原文件。"""
    p = Path(path).expanduser().resolve(strict=True)
    if not p.is_file():
        raise ImageToolError('需要本地图片文件')
    raw = p.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ImageToolError('图片超过 20MB')
    try:
        data, w, h = prepare_png_bytes(raw)
    except SafetyError as exc:
        raise ImageToolError(str(exc))
    return data, {'path': str(p), 'sha256': hashlib.sha256(data).hexdigest(),
                  'width': w, 'height': h, 'bytes': len(data)}





class ImageUI(WeChatUI):
    """独立适配器：每一步都绑定工具指定目标，不借用 target_chat 默认值。"""
    def checked(self, chat, guard):
        guard()
        image = self.verify_target(expected_chat=chat)
        if image.size != (1021, 740):
            raise SafetyError('窗口不是已支持的1021×740，拒绝猜坐标')
        return image

    # 剪贴板备份/恢复继承 WeChatUI（空剪贴板会自动按 ('none', b'') 处理）

    def send_png(self, data, chat, guard, mark_submitting):
        before = self.checked(chat, guard)
        if self._draft_text(before) or not composer_empty(before):
            raise SafetyError('输入区已有文字或图片，保留草稿并拒绝发送')
        original = self.clip_read()
        try:
            self.checked(chat, guard)
            self.clip_write('image/png', data)
            actual = self.run(['xclip', '-selection', 'clipboard', '-out', '-target', 'image/png'])
            if actual != data:
                raise SafetyError('剪贴板内容与冻结图片不符')
            self.checked(chat, guard)
            self.focus_window()                 # 不激活窗口时粘贴会静默失败
            ax, ay = self.last_abs
            self.run(['xdotool', 'mousemove', str(ax + 570), str(ay + 660)])
            self.run(['xdotool', 'click', '1'])
            self.checked(chat, guard)
            self.key('ctrl+v')
            time.sleep(1.5)
            preview = self.checked(chat, guard)
            if not preview_changed(before, preview):
                raise SafetyError('输入区未出现足够明确的新图片预览；未按发送键')
            # 最后一帧仍需有预览，避免用户手工改了草稿；不自动清除任何草稿。
            ready = self.checked(chat, guard)
            if not composer_stable(preview, ready):
                raise SafetyError('预览发生变化；未按发送键')
            mark_submitting()  # 必须先持久化不确定状态，才允许按 Return
            last = self.checked(chat, guard)
            if not composer_stable(ready, last):
                raise SafetyError('最终发送前预览变化，拒绝按发送键')
            self.key('Return')
            time.sleep(1.5)
            final = self.checked(chat, guard)
            if self._draft_text(final) or not composer_empty(final):
                raise SafetyError('发送后输入区未清空；结果不确定，禁止重试')
            return {'status': 'SUBMITTED', 'delivery_confirmed': False}
        finally:
            # 仍持有UI锁；不恢复窗口、不清理草稿。剪贴板恢复失败也按不确定处理。
            self.clip_write(*original)


def run_tool(chat, image, *, execute=False, confirm_chat=None, expected_sha256=None,
             request_id=None, config_path=CONFIG, state_dir=STATE, ui_factory=ImageUI,
             navigator_factory=ChatNavigator, lease_factory=ui_lease):
    state_dir = Path(state_dir)
    cfg = load_config(config_path)
    ck = authorize(cfg, chat)
    data, info = prepare_image(image)

    def guard():
        if (state_dir / 'STOP').exists():
            raise ImageToolError('STOP 已启用，禁止发送')
        current = load_config(config_path)
        if authorize(current, chat) != ck or current.get('display') != cfg.get('display'):
            raise ImageToolError('发送授权或显示配置已变化')

    guard()
    plan = dict(info, chat=chat, chat_key=ck, status='PREFLIGHT', ui_touched=False)
    if not execute:
        return plan
    if confirm_chat != chat or expected_sha256 != info['sha256']:
        raise ImageToolError('执行必须确认完全一致的会话名与预检 PNG sha256')
    if not request_id or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', request_id):
        raise ImageToolError('执行必须提供1–80位字母数字/下划线/短横线 request-id')
    fingerprint = hashlib.sha256((ck + ':' + info['sha256']).encode()).hexdigest()
    # 锁忙就直接让路，不写入操作记录、不动UI、不停止常驻服务。
    with lease_factory(state_dir):
        guard()
        folder = state_dir / 'image-tool'
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        dbpath = folder / 'attempts.sqlite'
        db = sqlite3.connect(dbpath, timeout=3)
        os.chmod(dbpath, 0o600)
        try:
            db.execute('CREATE TABLE IF NOT EXISTS attempts('
                       'request_id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE, chat TEXT, '
                       'sha256 TEXT, state TEXT, created REAL, updated REAL)')
            old = db.execute('SELECT state FROM attempts WHERE request_id=? OR fingerprint=?',
                             (request_id, fingerprint)).fetchone()
            if old:
                return dict(plan, status='DUPLICATE_BLOCKED', prior_state=old[0])
            with db:
                db.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?,?)',
                           (request_id, fingerprint, chat, info['sha256'], 'STARTED', time.time(), time.time()))

            def mark(status):
                with db:
                    db.execute('UPDATE attempts SET state=?,updated=? WHERE request_id=?',
                               (status, time.time(), request_id))

            try:
                guard()
                ui = ui_factory(cfg)
                navigator_factory(ui).switch_to(chat)
                result = ui.send_png(data, chat, guard, lambda: mark('SUBMITTING'))
                mark(result['status'])
                return dict(plan, **result, request_id=request_id, ui_touched=True)
            except BaseException:
                mark('UNCERTAIN')
                raise
        finally:
            db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description='独立发图：默认仅文件/授权预检，不操作UI；不接收远程URL或生图提示词')
    parser.add_argument('--chat', required=True, help='原样登记的会话名')
    parser.add_argument('--image', required=True, help='本地静态 PNG/JPEG/WebP 路径')
    parser.add_argument('--execute', action='store_true', help='明确执行一次图片发送')
    parser.add_argument('--confirm-chat')
    parser.add_argument('--sha256', help='预检返回的转换后 PNG sha256')
    parser.add_argument('--request-id', help='本次人工操作的唯一标识，重跑不会重复发送')
    args = parser.parse_args(argv)
    try:
        result = run_tool(args.chat, args.image, execute=args.execute,
                          confirm_chat=args.confirm_chat, expected_sha256=args.sha256,
                          request_id=args.request_id)
    except UILeaseBusy:
        print(json.dumps({'status':'BUSY', 'ui_touched':False, 'retry_safe':True}, ensure_ascii=False))
        return 3
    except Exception as exc:
        # 不打印载荷、凭据或堆栈；UNCERTAIN 的尝试需人工核查，不能换id自动重试。
        print(json.dumps({'status':'BLOCKED_OR_UNCERTAIN', 'error_type':type(exc).__name__,
                          'message':str(exc)[:180], 'retry_safe':False}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['status'] in ('PREFLIGHT', 'SUBMITTED') else 4


if __name__ == '__main__':
    raise SystemExit(main())
