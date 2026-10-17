import sys, json, time
sys.path.insert(0, 'src')
from pathlib import Path
from multimodal import StepPlan, STATE
import sqlite3
cfg = json.load(open('config/resident.json'))
db = sqlite3.connect(':memory:')
model = StepPlan(cfg, db)
media = sorted((Path.home()/'.local/state/wechat-bot/media').glob('gen-*.png'))
img = str(media[-1])
print('image:', img)
model.session_for('group:bench')
fresh = [{'direction': 'in', 'kind': 'text', 'text': '在吗'}]
ctx_noimg = {'recent_turns': [], 'timeline': [{'direction': 'in', 'kind': 'text', 'text': '你好'}]}
ctx_img = {'recent_turns': [], 'timeline': [
    {'direction': 'in', 'kind': 'text', 'text': '你好'},
    {'direction': 'in', 'kind': 'image', 'image_path': img, 'text': ''}]}
for label, ctx in (('无图', ctx_noimg), ('带1张图', ctx_img)):
    t0 = time.time()
    try:
        r = model.reply(fresh, [], [], chat_context=ctx)
        print('%s: %.2fs reply=%r' % (label, time.time()-t0, r[:40]))
    except Exception as e:
        print('%s: FAILED %s %s' % (label, type(e).__name__, str(e)[:100]))
