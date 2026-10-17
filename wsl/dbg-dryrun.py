"""验证朋友圈发布的四道闸门（dry_run 不碰 UI）。"""
import sys, os, json, sqlite3
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from pathlib import Path
from moment_release import MomentRelease

STATE = Path.home() / ".local" / "state" / "wechat-bot"
cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())["moments"]
coords = json.loads(Path(ROOT + "/config/moments-coords.json").read_text())
db = sqlite3.connect(str(STATE / "ledger.sqlite"))
rel = MomentRelease(db, None, composer=None, coords=coords, state_dir=STATE, cfg=cfg)

print("APPROVE:", (STATE / "APPROVE_MOMENT").exists(),
      "| PUBLISH_ATTEMPT:", (STATE / "PUBLISH_ATTEMPT").exists(),
      "| STOP:", (STATE / "STOP").exists())
try:
    res = rel._publish(3, dry_run=True)
    print("dry_run(3) -> OK:", json.dumps({k: str(v)[:60] for k, v in res.items()
                                           if k != "coords"}, ensure_ascii=False))
except Exception as exc:
    print("dry_run(3) -> %s: %s" % (type(exc).__name__, str(exc)[:150]))
d = rel.draft(3)
print("draft3:", d["state"], "| image:", d["image"][-32:], "| exists:", Path(d["image"]).exists())

# 令牌摘要绑定：改一个字符后应视为"未批准"
rel2 = MomentRelease(db, None, composer=None, coords=coords, state_dir=STATE, cfg=cfg)
db.execute("UPDATE moments SET text=text||' ' WHERE id=3")
db.commit()
try:
    rel2._publish(3, dry_run=True)
    print("tampered -> 竟然通过 ✗")
except Exception as exc:
    print("tampered -> 正确拒绝:", type(exc).__name__, str(exc)[:70])
db.execute("UPDATE moments SET text=rtrim(text) WHERE id=3")
db.commit()
