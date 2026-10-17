import sys
sys.path.insert(0, 'src')
from screen import list_x_windows
wins = list_x_windows(':99')
print('total', len(wins))
print('--- 1021x740 ---')
for w in wins:
    if (w['w'], w['h']) == (1021, 740):
        print(w)
print('--- title/class 含 wechat/WeChat/Weixin ---')
for w in wins:
    t = (w['title'] or '') + '|' + (w['classes'] or '')
    if 'wechat' in t.lower() or 'weixin' in t.lower():
        print(w)
print('--- 尺寸 >= 600x600 的 ---')
for w in wins:
    if w['w'] >= 600 and w['h'] >= 600:
        print(w)
