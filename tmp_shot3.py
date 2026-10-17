import sys, json, time
sys.path.insert(0, 'src')
from pathlib import Path
from wechat_ui import WeChatUI
from ui_lease import ui_lease
cfg = json.load(open('config/resident.json'))
STATE = Path.home() / '.local/state/wechat-bot'
with ui_lease(STATE):
    ui = WeChatUI(cfg)
    img = ui.capture()
    img.save('shots/now-state.png')
    print('saved', img.size)
