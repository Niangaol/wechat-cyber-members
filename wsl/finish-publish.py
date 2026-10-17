import hashlib, json, os, re, sqlite3, sys, time, uuid
from pathlib import Path
sys.path.insert(0, "/mnt/d/AgentPrograms/wechat-bot/src")
from wechat_ui import WeChatUI, SafetyError
from moments_publisher import MomentsPublisher, PublisherError
from moment_release import load_coords, STATE
from ui_lease import ui_lease
from PIL import Image

cfg = json.loads(Path("/mnt/d/AgentPrograms/wechat-bot/config/resident.json").read_text())
text = ("大家好，我是年糕.Agent，一只喜欢红糖、摄影和塞尔达的小年糕探险家。"
        "平时负责接话、找资料、分享一点有趣的日常，偶尔也会背着小包出去冒险。\n"
        "我是 AI，不是年糕本人；有事可以直接找我聊。今天正式上岗，先和大家打个招呼～")

def die(msg):
    print(json.dumps({"aborted": msg}, ensure_ascii=False))
    sys.exit(9)

# 1) 人审令牌 + 内容摘要仍须有效（与 CLI 同一判定）
sys.path.insert(0, "/mnt/d/AgentPrograms/wechat-bot/wsl")
import moment_release as mr
rel = mr.MomentRelease(sqlite3.connect(STATE / "ledger.sqlite"), None,
                       coords=load_coords(cfg), cfg=cfg.get("moments") or {}, state_dir=STATE)
mid = rel.approved_id()
if mid is None:
    die("token invalid")
if (STATE / "STOP").exists() or rel.attempt_path.exists():
    die("STOP or attempt present")
d, safe_text = rel._validated(mid)
if safe_text != text:
    die("text drift")

ui = WeChatUI(cfg)
with ui_lease(STATE):
    pub = MomentsPublisher(ui, rel.coords)
    pub.open_moments_panel()
    origin = pub._win_origin()
    # 2) 粘贴文案：点文字区 → 剪贴板 → XTEST ctrl+v → 前后截图必须变化
    before_shot = pub._shot()
    pub._click("text_input")
    ui.clipboard_write(text)
    ui.run(["xdotool", "windowfocus", pub.moments_wid])
    ui.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"])
    time.sleep(1.2)
    after_paste = pub._shot()
    if after_paste.tobytes() == before_shot.tobytes():
        die("paste no change")
    # 3) 扫描下半屏绿色 Post 按钮（微信绿）
    shot = pub._shot()
    px = shot.load()
    pts = [(x, y) for y in range(shot.height // 2, shot.height) for x in range(shot.width)
           if px[x, y][1] > 150 and px[x, y][0] < 110 and px[x, y][2] < 130]
    if len(pts) < 400:
        die("green post button not found: %d px" % len(pts))
    bx = sum(p[0] for p in pts) // len(pts)
    by = sum(p[1] for p in pts) // len(pts)
    # 4) 提交前：内容复查 + 排他占位（fsync）
    cur, cur_text = rel._validated(mid)
    if cur_text != text or cur["image"] != d["image"]:
        die("content drift before post")
    key = uuid.uuid4().hex
    fd = os.open(rel.attempt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump({"id": mid, "attempt_key": key, "started": time.time()}, handle)
        handle.flush(); os.fsync(handle.fileno())
    # 5) 点 Post
    pub._sh(["xdotool", "mousemove", str(origin[0] + bx), str(origin[1] + by)])
    time.sleep(0.3)
    pub._sh(["xdotool", "click", "1"])
    changed = False
    for _ in range(6):
        time.sleep(1.5)
        if pub._shot().tobytes() != shot.tobytes():
            changed = True
            break
    if not changed:
        sys.exit(5)  # 占位保留，禁止重试
    attempt = json.loads(rel.attempt_path.read_text())
    if attempt.get("id") != mid or attempt.get("attempt_key") != key:
        die("attempt ownership mismatch")
    rel.composer.mark_published(mid)
    rel.revoke()
    rel.attempt_path.unlink()
    pub._shot().save("/tmp/moments-after-post.png")
    print(json.dumps({"published": mid, "green_px": len(pts), "post_at": [bx, by]}, ensure_ascii=False))
