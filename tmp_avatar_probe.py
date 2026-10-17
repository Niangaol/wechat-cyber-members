import sys, json, time
sys.path.insert(0, 'src')
from pathlib import Path
from wechat_ui import WeChatUI
from chat_navigator import (ChatNavigator, avatar_rows, avatar_key, row_y_by_avatar,
                            find_chat_in_list)
from ui_lease import ui_lease
cfg = json.load(open('config/resident.json'))
STATE = Path.home() / '.local/state/wechat-bot'
with ui_lease(STATE):
    ui = WeChatUI(cfg); nav = ChatNavigator(ui)
    img = ui.capture()
    pos = find_chat_in_list(ui, img, '豆包')
    print('find_chat_in_list 豆包 ->', pos)
    if pos:
        y = pos[1]
        runs = avatar_rows(img)
        key = avatar_key(img, y, runs)
        print('key at text y:', key)
        # 同一帧里按头像找
        print('same frame lookup:', row_y_by_avatar(img, key))
        img2 = ui.capture()
        print('next frame lookup:', row_y_by_avatar(img2, key))
        print('runs:', len(runs), 'first:', runs[:3])
