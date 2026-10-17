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
    # 先切到一个别的会话，保证 很帅的年糕 不是当前会话
    nav.switch_to('人机')
    time.sleep(0.5)
    img0 = ui.capture()
    # 不用 hint，走完整查找，看它到底怎么找到的
    t0 = time.time()
    try:
        img = nav.switch_to('很帅的年糕')
        print('无 hint 切换 %.2fs y=%s' % (time.time()-t0, nav.last_row_y))
        if nav.last_row_y is not None:
            y = nav.last_row_y
            print('key=%s' % avatar_key(img, y))
    except Exception as e:
        print('无 hint 失败 %.2fs %s' % (time.time()-t0, str(e)[:80]))
    # 再切回人机，然后用 hint 试一次
    nav.switch_to('人机')
    time.sleep(0.3)
    img1 = ui.capture()
    y1 = row_y_by_avatar(img1, avatar_key(img, y)) if nav.last_row_y else None
    print('换回人机后，头像查找 很帅的年糕 ->', y1)
