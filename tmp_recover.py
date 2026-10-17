import sys, json, time
sys.path.insert(0, 'src')
from pathlib import Path
from wechat_ui import WeChatUI
from ui_lease import ui_lease, UILeaseBusy
cfg = json.load(open('config/resident.json'))
STATE = Path.home() / '.local/state/wechat-bot'
for a in range(30):
    try:
        lease = ui_lease(STATE); lease.__enter__(); break
    except UILeaseBusy:
        time.sleep(2)
else:
    print('BUSY'); raise SystemExit(3)
try:
    ui = WeChatUI(cfg)
    img = ui.capture()
    img.save('shots/before-recover.png')
    ax, ay = ui.last_abs
    # 左侧导航：聊天 tab（第二个图标，约 y=104）
    ui.run(['xdotool', 'mousemove', str(ax + 32), str(ay + 104)])
    ui.run(['xdotool', 'click', '1'])
    time.sleep(0.8)
    img2 = ui.capture()
    img2.save('shots/after-recover.png')
    print('clicked chat tab; saved')
finally:
    try: lease.__exit__()
    except Exception: pass
