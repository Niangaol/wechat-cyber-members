"""UI-TARS WSL 版操作子进程：截图用 import，键鼠用 xdotool（X11 原生，无 nut-js）。
用法：
  python3 uitars-x11-child.py screenshot [out.png]
  python3 uitars-x11-child.py action '<json>'
json: {"actions":[{"type":"click","x":100,"y":200},{"type":"type","text":"hi"}]}
"""
import base64, json, os, subprocess, sys, time

DISPLAY = os.environ.get('DISPLAY', ':99')
ENV = dict(os.environ, DISPLAY=DISPLAY)


def run(args, data=None, timeout=20):
    return subprocess.run(args, input=data, capture_output=True,
                          env=ENV, timeout=timeout, check=True).stdout


def screenshot(path=None):
    out = run(['import', '-window', 'root', 'png:-'], timeout=30)
    if path:
        with open(path, 'wb') as f:
            f.write(out)
        return path
    return out


def do_action(a):
    t = a.get('type')
    if t in ('click', 'double_click', 'right_click'):
        x, y = int(a['x']), int(a['y'])
        run(['xdotool', 'mousemove', str(x), str(y)])
        time.sleep(0.2)
        if t == 'double_click':
            run(['xdotool', 'click', '--repeat', '2', '--delay', '120', '1'])
        elif t == 'right_click':
            run(['xdotool', 'click', '3'])
        else:
            run(['xdotool', 'click', '1'])
    elif t == 'type':
        text = str(a.get('text', ''))
        if not text:
            return
        if all(ord(c) < 128 for c in text):
            run(['xdotool', 'type', '--clearmodifiers', '--delay', '30', text])
        else:
            subprocess.run(['xsel', '--clipboard', '--input'], input=text.encode('utf-8'),
                           env=ENV, timeout=10, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            run(['xdotool', 'key', '--clearmodifiers', 'ctrl+v'])
    elif t == 'key':
        run(['xdotool', 'key', '--clearmodifiers', str(a.get('key', ''))])
    elif t == 'hotkey':
        keys = '+'.join(str(k) for k in a.get('keys', []))
        run(['xdotool', 'key', '--clearmodifiers', keys])
    elif t == 'scroll':
        x, y = int(a['x']), int(a['y'])
        amount = int(a.get('amount', 3))
        btn = '4' if a.get('direction', 'down') == 'up' else '5'
        run(['xdotool', 'mousemove', str(x), str(y)])
        for _ in range(abs(amount)):
            run(['xdotool', 'click', btn])
            time.sleep(0.1)
    elif t == 'drag':
        run(['xdotool', 'mousemove', str(int(a['x'])), str(int(a['y']))])
        time.sleep(0.2)
        run(['xdotool', 'mousedown', '1'])
        time.sleep(0.1)
        run(['xdotool', 'mousemove', str(int(a['x2'])), str(int(a['y2']))])
        time.sleep(0.2)
        run(['xdotool', 'mouseup', '1'])
    elif t == 'wait':
        time.sleep(float(a.get('seconds', 1)))
    else:
        raise ValueError('未知动作类型: %s' % t)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'screenshot':
        out = sys.argv[2] if len(sys.argv) > 2 else None
        data = screenshot(out)
        if out:
            print('SAVED', out)
        else:
            sys.stdout.buffer.write(base64.b64encode(data))
    elif cmd == 'action':
        spec = json.loads(sys.argv[2])
        acts = spec.get('actions', spec if isinstance(spec, list) else [])
        for a in acts:
            do_action(a)
            time.sleep(0.15)
        print('ACTIONS_DONE', len(acts))
    else:
        print('未知命令:', cmd)
        sys.exit(1)


if __name__ == '__main__':
    main()
