import sys, json
from pathlib import Path
sys.path.insert(0, '/mnt/d/AgentPrograms/wechat-bot/src')
from wechat_ui import WeChatUI
from chat_navigator import find_chat_in_list, ocr_tsv, _list_match

cfg = json.loads(Path('/mnt/d/AgentPrograms/wechat-bot/config/resident.json').read_text())
ui = WeChatUI(cfg)
img = ui.capture()
print('窗口:', img.size, 'abs:', getattr(ui, 'last_abs', None))
region = img.crop((60, 60, 340, 555))
words = ocr_tsv(ui, region)
print('列表 OCR 词数:', len(words))
for t, x, y, w, h in words[:30]:
    mark = ' <== 匹配' if _list_match('很帅的年糕', t) or _list_match('测试群', t) else ''
    print('  (%d,%d) %r%s' % (x, y, t, mark))
for name in ('很帅的年糕', '测试群'):
    print(name, '->', find_chat_in_list(ui, img, name))
