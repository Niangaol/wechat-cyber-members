"""只读运行就绪快照：不建库、不改令牌、不操作微信、不请求模型。"""
import json
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = Path.home() / '.local' / 'state' / 'wechat-bot'


def snapshot(root=ROOT, state=STATE):
    root, state = Path(root), Path(state)
    cfg = json.loads((root / 'config' / 'resident.json').read_text())
    out = {
        'policy': {
            'watch_chats': cfg.get('watch_chats', []),
            'group_whitelist': cfg.get('group_whitelist', []),
            'direct_policy': cfg.get('direct_policy'),
            'direct_blacklist_count': len(cfg.get('direct_blacklist') or []),
            'automation': cfg.get('automation', {}),
            'interaction_enabled': (cfg.get('interact') or {}).get('enabled', False),
            'interaction_friends_count': len((cfg.get('interact') or {}).get('friends') or []),
            'image_generation_config_enabled': (cfg.get('image_generation') or {}).get('enabled'),
        },
        'stop_present': (state / 'STOP').is_file(),
        'publication_attempt_present': (state / 'PUBLISH_ATTEMPT').exists(),
        'approval_present': {name: (state / name).is_file() for name in ('APPROVE_MOMENT', 'APPROVE_INTERACT')},
        'ledger_exists': (state / 'ledger.sqlite').is_file(),
    }
    if out['ledger_exists']:
        db = sqlite3.connect((state / 'ledger.sqlite').resolve().as_uri() + '?mode=ro', uri=True)
        try:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            counts = {}
            for table in ('moments', 'moment_inbox', 'interaction_attempts'):
                if table in tables:
                    counts[table] = dict(db.execute('SELECT state,count(*) FROM ' + table + ' GROUP BY state'))
            out['ledger_states'] = counts
            if 'moments' in tables:
                out['published_with_timestamp'] = db.execute(
                    "SELECT count(*) FROM moments WHERE state='PUBLISHED' AND published>0").fetchone()[0]
            if 'interaction_attempts' in tables:
                out['blocked_attempts'] = [dict(zip(('id', 'state', 'started'), r)) for r in db.execute(
                    "SELECT mid,state,started FROM interaction_attempts WHERE state IN ('STARTED','UNCERTAIN')")]
        finally:
            db.close()
    return out


def service_states():
    results = {}
    for name in ('wechat-stack', 'wechat-bot'):
        proc = subprocess.run(['systemctl', '--user', 'show', name, '--property=ActiveState',
                               '--property=SubState', '--property=UnitFileState'],
                              capture_output=True, text=True, timeout=10, check=False)
        results[name] = {'returncode': proc.returncode, 'properties': dict(
            line.split('=', 1) for line in proc.stdout.splitlines() if '=' in line)}
    return results


if __name__ == '__main__':
    report = snapshot()
    report['services'] = service_states()
    print(json.dumps(report, ensure_ascii=False, indent=2))
