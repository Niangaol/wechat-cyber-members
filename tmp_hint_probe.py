import sys, json, time, logging
sys.path.insert(0, 'src')
from pathlib import Path
from wechat_ui import WeChatUI
from chat_navigator import ChatNavigator, avatar_key, row_band_sig, row_y_by_avatar
from ui_lease import ui_lease
logging.basicConfig(level=logging.INFO, format='%(message)s')
cfg = json.load(open('config/resident.json'))
STATE = Path.home() / '.local/state/wechat-bot'
with ui_lease(STATE):
    ui = WeChatUI(cfg); nav = ChatNavigator(ui)
    t0=time.time(); img = nav.switch_to('很帅的年糕'); print('r1 %.2fs y=%s' % (time.time()-t0, nav.last_row_y))
    y = nav.last_row_y; key = avatar_key(img, y); sig = row_band_sig(img, y)
    print('cached key=%s y=%s' % (key, y))
    for rnd in (2, 3):
        nav.pending_hint = (y, sig, key)
        img0 = ui.capture()
        found = row_y_by_avatar(img0, key)
        print('r%d 预查: avatar lookup -> %s' % (rnd, found))
        t0=time.time()
        try:
            img2 = nav.switch_to('很帅的年糕')
            print('r%d %.2fs OK y=%s' % (rnd, time.time()-t0, nav.last_row_y))
            y = nav.last_row_y; key = avatar_key(img2, y); sig = row_band_sig(img2, y)
        except Exception as e:
            print('r%d FAILED %.2fs %s: %s' % (rnd, time.time()-t0, type(e).__name__, str(e)[:80]))
            break
