import json, time
from pathlib import Path
state = Path.home() / ".local/state/wechat-bot"
seed = {
    "baselines": {"group:Agent 聊天测试群": [], "direct:很帅的年糕": []},
    "seen": {"group:Agent 聊天测试群": [], "direct:很帅的年糕": []},
    "saved_at": time.time(),
    "note": "manual seed: user-approved full-auto test; visible backlog treated as one fresh batch per chat",
}
(state / "baselines.json").write_text(json.dumps(seed, ensure_ascii=False, indent=2))
print("seeded")
