import sys, json, time
sys.path.insert(0, 'src')
from pathlib import Path
from wechat_ui import WeChatUI
from chat_navigator import ChatNavigator, row_band_sig, avatar_key
from ui_lease import ui_lease
cfg = json.load(open('config/resident.json'))
STATE = Path.home() / '.local/state/wechat-bot'
names = ['很帅的年糕', 'Deepseek', '人在月球有点冷', '李想26计科', '豆包', '阿比盖尔 威廉姆斯', 'Agent 聊天测试群', '人机']
with ui_lease(STATE):
    ui = WeChatUI(cfg)
    nav = ChatNavigator(ui)
    cache = {}
    for rnd in (1, 2, 3):
        total = 0; slow = 0
        for name in names:
            h = cache.get(name)
            if h:
                nav.pending_hint = h
            t0 = time.time(); img = nav.switch_to(name); dt = time.time()-t0
            total += dt
            if dt > 2.0: slow += 1
            if nav.last_row_y is not None:
                y = nav.last_row_y
                cache[name] = (y, row_band_sig(img, y), avatar_key(img, y))
            print('r%d %-16s %.2fs' % (rnd, name, dt))
        print('round%d total=%.1fs slow=%d/%d' % (rnd, total, slow, len(names)))
