import sys, json, time
sys.path.insert(0, 'src')
from pathlib import Path
from wechat_ui import WeChatUI
from chat_navigator import ChatNavigator, avatar_rows, avatar_key, row_y_by_avatar, row_band_sig
from ui_lease import ui_lease
cfg = json.load(open('config/resident.json'))
STATE = Path.home() / '.local/state/wechat-bot'
with ui_lease(STATE):
    ui = WeChatUI(cfg); nav = ChatNavigator(ui)
    name = '阿比盖尔 威廉姆斯'
    # 先用一次普通切换建立 hint
    t0=time.time(); img = nav.switch_to(name); print('first switch %.2fs' % (time.time()-t0))
    y = nav.last_row_y
    key = avatar_key(img, y)
    print('cached y=%s key=%s' % (y, key))
    for rnd in (1, 2):
        t0=time.time(); img = ui.capture(); t_cap=time.time()-t0
        t0=time.time(); m = nav._matches_title(img, name); t_match=time.time()-t0
        t0=time.time(); yy = row_y_by_avatar(img, key); t_av=time.time()-t0
        print('round%d cap=%.2f match=%.2f(%s) avatar=%.2f(y=%s)' % (rnd, t_cap, t_match, m, t_av, yy))
        if yy is None:
            print('  avatar miss -> fallback'); break
        ax, ay = ui.last_abs
        ui.run(['xdotool','mousemove', str(ax+160), str(ay+yy)])
        t0=time.time(); ui.run(['xdotool','click','1']); time.sleep(0.35); t_click=time.time()-t0
        img2 = ui.capture()
        t0=time.time(); ok = nav._matches_title(img2, name); t_v=time.time()-t0
        print('  click=%.2f verify=%.2f(%s)' % (t_click, t_v, ok))
