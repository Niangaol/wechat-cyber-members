"""Activate the WeChat window then click; used when clicks silently do nothing."""
import json, subprocess, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from screen import list_x_windows
DISPLAY = ':99'
ENV = dict(__import__('os').environ, DISPLAY=DISPLAY)
x, y = int(sys.argv[1]), int(sys.argv[2])
label = sys.argv[3] if len(sys.argv) > 3 else 'click'
wins = [w for w in list_x_windows(DISPLAY) if w['title'] in ('Weixin', 'wechat')]
if not wins:
    print(json.dumps({'error': 'no wechat window'})); raise SystemExit(1)
w = max(wins, key=lambda w: w['w']*w['h'])
print(json.dumps({'window': w['id'], 'size': [w['w'], w['h']], 'pos': [w['x'], w['y']],
                  'click': [x, y], 'label': label}), flush=True)
for cmd in (['xdotool', 'windowactivate', '--sync', w['id']],
            ['xdotool', 'windowfocus', '--sync', w['id']],
            ['xdotool', 'mousemove', str(x), str(y)],
            ['xdotool', 'click', '1']):
    r = subprocess.run(cmd, capture_output=True, text=True, env=ENV, timeout=20)
    print(json.dumps({'cmd': ' '.join(cmd[:3]), 'rc': r.returncode,
                      'stderr': r.stderr.strip()[:120]}), flush=True)
    time.sleep(0.4)
