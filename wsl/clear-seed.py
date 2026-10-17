import json, time
from pathlib import Path
STATE = Path.home() / '.local/state/wechat-bot'
p = STATE / 'baselines.json'
data = json.loads(p.read_text())
backup = STATE / ('baselines.json.bak-' + str(int(time.time())))
backup.write_text(json.dumps(data, ensure_ascii=False))
p.chmod(0o600)
# 人工种子没有真实基线内容，视为无效种子：移除，让常驻重新建基线（不回放历史）
if data.get('note', '').startswith('manual seed'):
    p.unlink()
    print('removed manual seed; backup at', backup.name)
else:
    print('kept existing baselines (not a manual seed)')