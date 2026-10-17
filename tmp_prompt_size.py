import sys
sys.path.insert(0, 'src')
from pathlib import Path
p = Path('config/persona.md')
text = p.read_text(encoding='utf-8')
print('persona chars:', len(text))
print('persona head:', repr(text[:120]))
import json
cfg = json.load(open('config/resident.json'))
print('reply_max_chars:', cfg.get('reply_max_chars'))
