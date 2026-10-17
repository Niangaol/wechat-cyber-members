import sys, json, time
sys.path.insert(0, 'src')
from pathlib import Path
from wechat_ui import WeChatUI
from chat_navigator import ChatNavigator, avatar_rows, avatar_key, row_y_by_avatar
from chat_anchors import find_list_anchor
from ui_lease import ui_lease
cfg = json.load(open('config/resident.json'))
STATE = Path.home() / '.local/state/wechat-bot'
with ui_lease(STATE):
    ui = WeChatUI(cfg); nav = ChatNavigator(ui)
    nav.switch_to('人机')
    time.sleep(0.4)
    img = ui.capture()
    pos = find_list_anchor('很帅的年糕', img)
    print('anchor 很帅的年糕 ->', pos)
    if pos:
        y = pos[1]
        crop = img.crop((121, max(0, y-18), 300, min(img.height, y+22)))
        print('该行 OCR =', repr(ui.ocr(crop, 7)))
    print('--- 可见行 OCR ---')
    for (top, bot) in avatar_rows(img):
        cy = (top + bot)//2
        crop = img.crop((121, max(0, cy-18), 300, min(img.height, cy+20)))
        print('y=%d %r' % (cy, (ui.ocr(crop, 7) or '')[:24]))
