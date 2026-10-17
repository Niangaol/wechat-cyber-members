import sys, json, time
sys.path.insert(0, 'src')
from pathlib import Path
from wechat_ui import WeChatUI
from chat_navigator import (ChatNavigator, avatar_rows, avatar_key, row_y_by_avatar,
                            row_band_sig)
from ui_lease import ui_lease
cfg = json.load(open('config/resident.json'))
STATE = Path.home() / '.local/state/wechat-bot'
with ui_lease(STATE):
    ui = WeChatUI(cfg); nav = ChatNavigator(ui)
    nav.switch_to('很帅的年糕')
    img = ui.capture()
    y = nav.last_row_y
    key = avatar_key(img, y)
    print('很帅的年糕 last_row_y=%s key=%s' % (y, key))
    runs = avatar_rows(img)
    print('rows=%d' % len(runs))
    keys = {}
    for (top, bot) in runs:
        cy = (top + bot) // 2
        k = avatar_key(img, cy, runs)
        keys.setdefault(k, []).append(cy)
        mark = ' <== 很帅的年糕' if k == key else ''
        print('  y=%d key=%s%s' % (cy, k, mark))
    dup = {k: v for k, v in keys.items() if len(v) > 1}
    print('duplicate keys:', dup)
    print('lookup by key ->', row_y_by_avatar(img, key))
