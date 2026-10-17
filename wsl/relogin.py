#!/usr/bin/env python3
"""掉登录后的一键恢复：认出客户端停在哪一步，需要时替你点一下 "Log In"。

背景（2026-10-17）：重启 wechat-stack 会让客户端回到登录窗——**账号还记着，
不需要扫码**，点一下 Log In、再在手机上确认即可。这个脚本把"点一下"自动化。

用法：
    DISPLAY=:99 python3 wsl/relogin.py            # 看状态；停在登录窗就点 Log In
    DISPLAY=:99 python3 wsl/relogin.py --check    # 只看状态，什么都不点
"""
import argparse
import io
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
import numpy as np                                     # noqa: E402
from PIL import Image                                  # noqa: E402
from screen import list_x_windows                      # noqa: E402

MAIN_W, MAIN_H = 1021, 740          # 登录后的主窗口尺寸；登录窗是 ~292x396


def wechat_window(display):
    wins = [w for w in list_x_windows(display) if w['title'] == 'Weixin']
    if not wins:
        return None
    return max(wins, key=lambda w: w['w'] * w['h'])


def grab(display, win):
    """截整个 root 再按窗口绝对坐标裁——比按窗口 id 截更省事，也更稳。"""
    raw = subprocess.run(['import', '-window', 'root', 'png:-'],
                         capture_output=True, env={'DISPLAY': display,
                                                   'PATH': '/usr/bin:/bin'},
                         timeout=30).stdout
    img = Image.open(io.BytesIO(raw)).convert('RGB')
    x, y = max(0, win['abs_x']), max(0, win['abs_y'])
    return img.crop((x, y, x + win['w'], y + win['h'])), (x, y)


def ocr_text(image, psm=6):
    """和机器人用同一条 OCR 路径（tesseract 走 stdin），不额外装 pytesseract。"""
    buf = io.BytesIO()
    image.save(buf, format='PNG')
    r = subprocess.run(['tesseract', 'stdin', 'stdout', '-l', 'chi_sim+eng',
                        '--psm', str(psm)],
                       input=buf.getvalue(), capture_output=True,
                       env={'PATH': '/usr/bin:/bin'}, timeout=30)
    return r.stdout.decode('utf-8', 'replace').strip()


def find_green_button(image):
    """微信绿按钮：绿通道高、红蓝明显更低。返回 (x, y) 或 None（图内坐标）。"""
    a = np.asarray(image, dtype='int16')
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    mask = (g > 140) & (g - r > 45) & (g - b > 45)
    ys, xs = np.nonzero(mask)
    if len(xs) < 200:                                   # 太小的绿点不算按钮
        return None
    return (int(xs.min() + xs.max()) // 2, int(ys.min() + ys.max()) // 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--display', default=':99')
    ap.add_argument('--check', action='store_true', help='只看状态，不点击')
    args = ap.parse_args()

    win = wechat_window(args.display)
    if win is None:
        print('❌ 没找到微信窗口：客户端可能没起来（看 systemctl --user status wechat-stack）')
        return 2
    size = '%dx%d' % (win['w'], win['h'])
    if win['w'] >= MAIN_W - 40 and win['h'] >= MAIN_H - 40:
        print('✅ 已登录（主窗口 %s）——机器人会自己继续，不需要做任何事' % size)
        return 0

    image, (ox, oy) = grab(args.display, win)
    text = ocr_text(image)
    print('窗口 %s · OCR: %s' % (size, ' / '.join(t.strip() for t in text.splitlines() if t.strip())))

    if 'confirm on phone' in text.lower():
        print('⏳ 客户端正在等手机确认：请在手机微信里点「确认登录」（不用扫码）。')
        print('   如果手机上没看到提示：到 http://127.0.0.1:6080/vnc.html 点一下 Cancel，再跑一次本脚本。')
        return 1

    if 'scan' in text.lower():
        print('📱 客户端在等扫码登录（手机上：微信 → 右上角 + → 扫一扫）。')
        print('   二维码显示在这台电脑的屏幕上：http://127.0.0.1:6080/vnc.html')
        print('   （手机确认登录的提示过期后就会回到这一步；扫一次即可，账号不用重新输）')
        print('   若提示二维码已失效：在虚拟屏里点一下二维码刷新，再扫。')
        return 1

    button = find_green_button(image)
    low = text.lower()
    if 'log in' not in low or button is None:
        print('⚠️ 认不出当前界面（既不是登录窗也不是主窗口），没有动它。请开虚拟屏看一眼：')
        print('   http://127.0.0.1:6080/vnc.html')
        return 3

    if args.check:
        print('（--check）检测到登录按钮，位置图内 %s，没有点击' % (button,))
        return 0
    if button is None:
        print('⚠️ 有 Log In 字样但找不到绿色按钮，放弃点击（避免瞎点）。')
        return 3

    bx, by = ox + button[0], oy + button[1]
    print('→ 点击 Log In @ (%d, %d)' % (bx, by))
    for cmd in (['xdotool', 'mousemove', str(bx), str(by)],
                ['xdotool', 'click', '1']):
        subprocess.run(cmd, env={'DISPLAY': args.display, 'PATH': '/usr/bin:/bin'}, timeout=15)
        time.sleep(0.6)
    time.sleep(5)
    win2 = wechat_window(args.display)
    if win2 and win2['w'] >= MAIN_W - 40:
        print('✅ 已登录（%dx%d）' % (win2['w'], win2['h']))
        return 0
    print('⏳ 已点登录，现在请在手机微信里确认（不需要扫码）。')
    return 1


if __name__ == '__main__':
    sys.exit(main())
