"""List models available on the configured StepFun-compatible endpoint."""
import json, os, sys, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from multimodal import StepPlan
cfg = json.loads((ROOT/'config'/'resident.json').read_text())
model = StepPlan(cfg)
key = model.key()
if not key:
    print('NO_KEY'); sys.exit(1)
base = cfg['step_plan']['base_url'].rstrip('/')
req = urllib.request.Request(base + '/models', headers={'Authorization': 'Bearer ' + key})
try:
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())
    ids = [m.get('id') for m in data.get('data', [])]
    print(json.dumps({'count': len(ids), 'ids': ids}, ensure_ascii=False, indent=1))
except Exception as e:
    print(json.dumps({'error': type(e).__name__, 'detail': str(e)[:300]}))
