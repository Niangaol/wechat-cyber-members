import json
from pathlib import Path
s = json.loads((Path.home()/'.local'/'state'/'wechat-bot'/'status.json').read_text())
print('resident state:', s['state'], '| queue:', s['queue_depth'], '| key:', s.get('model_key_present'))
