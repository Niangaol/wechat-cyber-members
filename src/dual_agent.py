"""双 Agent 协作：UI-TARS（定位操作）+ StepPlan（写内容）。
UI-TARS 本地 VLM 跑在 WSL（127.0.0.1:8088），直接操作 :99 虚拟屏。
"""
import base64, json, os, re, subprocess, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'src'))
DISPLAY = ':99'
VLM = 'http://127.0.0.1:8088/v1'


def x11_screenshot(path=None):
    cmd = ['python3', str(ROOT/'wsl'/'uitars-x11-child.py'), 'screenshot']
    if path:
        cmd.append(path)
    r = subprocess.run(cmd, capture_output=True, timeout=60, env=dict(os.environ, DISPLAY=DISPLAY))
    if r.returncode != 0:
        raise RuntimeError('截图失败: ' + r.stderr.decode('utf-8', 'ignore')[:200])
    return path or r.stdout


def x11_action(spec):
    r = subprocess.run(['python3', str(ROOT/'wsl'/'uitars-x11-child.py'), 'action', json.dumps(spec)],
                       capture_output=True, timeout=60, env=dict(os.environ, DISPLAY=DISPLAY))
    if r.returncode != 0:
        raise RuntimeError('动作失败: ' + r.stderr.decode('utf-8', 'ignore')[:200])
    return r.stdout.decode()


def uitars_ask(task, shot_path='/tmp/dual-uitars.png'):
    """让本地 UI-TARS 看 :99 屏幕并回答/输出动作。"""
    x11_screenshot(shot_path)
    b64 = base64.b64encode(open(shot_path, 'rb').read()).decode()
    messages = [
        {'role': 'system', 'content': 'You are a GUI agent. Look at the screenshot and '
         'perform the task. Output ONLY a JSON array of actions like '
         '[{"type":"click","x":100,"y":200}]. Do not explain.'},
        {'role': 'user', 'content': [
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + b64}},
            {'type': 'text', 'text': task},
        ]},
    ]
    payload = {'model': 'ui-tars', 'messages': messages, 'max_tokens': 512,
               'temperature': 0.1, 'stream': False}
    req = urllib.request.Request(VLM + '/chat/completions', json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read())
    text = data['choices'][0]['message']['content'].strip()
    if text.startswith(chr(96)*3):
        text = re.sub(r'^`{3}(?:json)?s*|s*`{3}$', '', text).strip()
    return text


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'screenshot'
    if cmd == 'screenshot':
        print(x11_screenshot('/tmp/dual-test.png'))
    elif cmd == 'ask':
        task = sys.argv[2] if len(sys.argv) > 2 else '描述你看到的界面'
        try:
            print('UITARS_SAYS:', uitars_ask(task)[:500])
        except Exception as e:
            print('ASK_FAILED:', type(e).__name__, str(e)[:200])
