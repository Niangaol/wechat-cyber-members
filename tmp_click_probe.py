import sys, json, time
sys.path.insert(0, 'src')
from pathlib import Path
from wechat_ui import WeChatUI, normalize
from chat_anchors import find_list_anchor
from ui_lease import ui_lease
cfg = json.load(open('config/resident.json'))
STATE = Path.home() / '.local/state/wechat-bot'
with ui_lease(STATE):
    ui = WeChatUI(cfg)
    img = ui.capture()
    pos = find_list_anchor('很帅的年糕', img)
    print('anchor ->', pos)
    ax, ay = ui.last_abs
    ui.run(['xdotool', 'mousemove', str(ax + pos[0]), str(ay + pos[1])])
    ui.run(['xdotool', 'click', '1'])
    time.sleep(1.0)
    img2 = ui.capture()
    img2.save('shots/after-click484.png')
    print('title OCR =', repr(normalize(ui.ocr(img2.crop((283, 20, 700, 61)), 7))))
