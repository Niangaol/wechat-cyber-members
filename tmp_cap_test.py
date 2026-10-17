import sys, time
sys.path.insert(0, 'src')
import json
from wechat_ui import WeChatUI, UIUnavailable
cfg = json.load(open('config/resident.json'))
ui = WeChatUI(cfg)
wins = ui._weixin_windows(cfg)
print('matched windows:', [(w['id'], w['title'], w['w'], w['h']) for w in wins])
t0 = time.time()
try:
    img = ui.capture()
    print('capture OK %.2fs size=%s wid=%s abs=%s' % (time.time()-t0, img.size, ui.wid, ui.last_abs))
except Exception as e:
    print('capture FAILED %.2fs %s: %s' % (time.time()-t0, type(e).__name__, str(e)[:120]))
