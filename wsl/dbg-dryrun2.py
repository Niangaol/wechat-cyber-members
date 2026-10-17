"""朋友圈发布闸门：批准→通过；改内容→失效（摘要绑定，实测）。"""
import sys, json, sqlite3
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from pathlib import Path
from moment_release import MomentRelease

STATE = Path.home() / ".local" / "state" / "wechat-bot"
cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())["moments"]
coords = json.loads(Path(ROOT + "/config/moments-coords.json").read_text())
db = sqlite3.connect(str(STATE / "ledger.sqlite"))
rel = MomentRelease(db, None, composer=None, coords=coords, state_dir=STATE, cfg=cfg)

print("1) 重新批准（挂配图后摘要变了，旧令牌已自动失效——这是设计）")
rel.approve(3)
print("   token:", (STATE / "APPROVE_MOMENT").read_text()[:80])

print("2) dry_run 应通过")
try:
    res = rel._publish(3, dry_run=True)
    print("   OK approved=%s dry_run=%s id=%s text=%s..." % (
        res["approved"], res["dry_run"], res["id"], res["text"][:24]))
except Exception as exc:
    print("   FAIL %s: %s" % (type(exc).__name__, str(exc)[:100]))

print("3) 偷偷改一个字后应失效")
db.execute("UPDATE moments SET text=text||'！' WHERE id=3")
db.commit()
try:
    rel._publish(3, dry_run=True)
    print("   ✗ 竟然还通过")
except Exception as exc:
    print("   ✓ 正确拒绝:", str(exc)[:70])
db.execute("UPDATE moments SET text=rtrim(text, char(65281)) WHERE id=3")
db.commit()

print("4) 复核当前状态")
d = rel.draft(3)
print("   draft3:", d["state"], "| image ok:", Path(d["image"]).exists(),
      "| token valid:", rel.approved_id() == 3)
