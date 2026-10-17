import sys, json, time, logging
sys.path.insert(0, 'src')
from pathlib import Path
from wechat_ui import WeChatUI
from chat_navigator import (ChatNavigator, avatar_key, row_band_sig, row_y_by_avatar,
                            avatar_rows)
from ui_lease import ui_lease
logging.basicConfig(level=logging.INFO, format='%(message)s')
cfg = json.load(open('config/resident.json'))
STATE = Path.home() / '.local/state/wechat-bot'
with ui_lease(STATE):
    ui = WeChatUI(cfg); nav = ChatNavigator(ui)
    img = nav.switch_to('很帅的年糕')
    y = nav.last_row_y; key = avatar_key(img, y); sig = row_band_sig(img, y)
    print('基线 y=%s key=%s' % (y, key))
    nav.switch_to('人机')
    time.sleep(0.4)
    f = ui.capture()
    print('当前可见行:', [ (t+b)//2 for t,b in avatar_rows(f) ])
    print('头像查找(很帅的年糕) ->', row_y_by_avatar(f, key))
    nav.pending_hint = (y, sig, key)
    t0 = time.time()
    try:
        img2 = nav.switch_to('很帅的年糕')
        print('带 hint 切换 OK %.2fs y=%s' % (time.time()-t0, nav.last_row_y))
    except Exception as e:
        print('带 hint 切换失败 %.2fs: %s' % (time.time()-t0, str(e)[:90]))
