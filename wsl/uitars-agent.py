"""WSL 侧 UI-TARS Agent 循环：截图(X11 root) → 本地 llama-server → xdotool 执行 → 再截图。

与 Windows 侧 ui-tars-mcp 的区别：那个看 Windows 桌面，这个看 WSL Xvfb :99 的屏
（微信就在上面）。模型服务跑在 WSL 内的 llama-server（CUDA，RTX 5070 Ti）。

坐标约定（与 @ui-tars/action-parser 一致）：模型输出 0-1000 千分比刻度，
这里除以 1000 再乘 Xvfb 分辨率(1280x800) 换成像素。

用法:
  python3 uitars-agent.py "任务描述" [--max-steps 25] [--dry-run]
  python3 uitars-agent.py --check           # 只检查服务与截图是否正常

输出格式（UI-TARS）:
  Thought: ...
  Action: click(start_box='[x1, y1, x2, y2]')   # 0-1000 千分比
  Action: type(content='...')
  Action: hotkey(key='ctrl a')
  Action: scroll(start_box='...', direction='down')
  Action: finished(content='...')
  Action: wait()

安全设计：
  --dry-run 只打印将执行的动作，不真的点；
  每一步动作都记日志（含截图存档到 /tmp/uitars-runs/），可复盘；
  坐标换算后超界直接拒绝执行。
"""
import argparse
import base64
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT / 'src')]

# DISPLAY 从项目配置读，环境变量优先（与 wechat_ui 一致）
DISPLAY = os.environ.get('DISPLAY') or ':99'
try:
    DISPLAY = json.loads((ROOT / 'config' / 'resident.json').read_text()).get('display', DISPLAY)
except Exception:
    pass
ENV = dict(os.environ, DISPLAY=DISPLAY)
BASE_URL = os.environ.get('UITARS_BASE_URL', 'http://127.0.0.1:8088/v1')
MODEL = os.environ.get('UITARS_MODEL', 'ui-tars')
SCREEN_W, SCREEN_H = 1280, 800          # Xvfb :99 的分辨率
LOG_DIR = Path('/tmp/uitars-runs')

ACTION_SPACES = (
    "click(start_box='[x1, y1, x2, y2]')\n"
    "left_double(start_box='[x1, y1, x2, y2]')\n"
    "right_single(start_box='[x1, y1, x2, y2]')\n"
    "drag(start_box='[x1, y1, x2, y2]', end_box='[x3, y3, x4, y4]')\n"
    "hotkey(key='')\n"
    "type(content='')\n"
    "scroll(start_box='[x1, y1, x2, y2]', direction='down or up or right or left')\n"
    "wait()\n"
    "finished()\n"
    "call_user()"
)

COORD_HINT = (
    "\n\n## Coordinate System (CRITICAL - read carefully)\n"
    "All coordinates inside start_box / end_box MUST be integers on a 0-1000 thousandth scale:\n"
    "- The top-left corner of the screen is (0, 0); the bottom-right corner is (1000, 1000).\n"
    "- x grows to the right, y grows downward.\n"
    "- NEVER use 0-1 decimals such as 0.018. NEVER use raw pixel values such as 35.\n"
    "- If unsure, estimate the position as a percentage of the screen and multiply by 10\n"
    "  (e.g. 2.5% from the left edge -> 25)."
)


def build_system_prompt():
    return "\n".join([
        'You are a GUI agent. You are given a task and your action history, with screenshots.',
        'You need to perform the next action to complete the task.',
        '',
        '## Output Format',
        'Thought: ...',
        'Action: ...',
        '',
        '## Action Space',
        ACTION_SPACES,
        COORD_HINT,
        '## Note',
        '- Write a small plan and finally summarize your next action (with its target element) in one sentence in the Thought part.',
        '- Output exactly ONE action per turn.',
        '',
        '## User Instruction',
        '',
    ])


class AgentError(RuntimeError):
    pass


def sh(args, data=None, timeout=30, check=True):
    p = subprocess.run(args, input=data, capture_output=True, timeout=timeout, env=ENV)
    if check and p.returncode != 0:
        raise AgentError('命令失败 %s: %s' % (args[:2], p.stderr.decode()[:200]))
    return p.stdout


def screenshot(path=None):
    """抓 Xvfb 整个根窗口（微信所有窗口都在上面）；有 --crop 时裁到目标窗口。"""
    raw = sh(['import', '-window', 'root', 'png:-'], timeout=40)
    im = Image.open(io.BytesIO(raw)).convert('RGB')
    if CROP:
        ox, oy, cw, ch = CROP
        im = im.crop((ox, oy, ox + cw, oy + ch))   # PIL 要 right/bottom，不是宽高
    if path:
        im.save(path)
    return im


def image_b64(im, max_side=1280):
    if max(im.size) > max_side:
        im.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, 'PNG')
    return base64.b64encode(buf.getvalue()).decode()


def ask_model(im, instruction):
    """把截图+指令发给 llama-server，返回原始文本。"""
    msgs = [
        {'role': 'system', 'content': build_system_prompt()},
        {'role': 'user', 'content': [
            {'type': 'image_url',
             'image_url': {'url': 'data:image/png;base64,' + image_b64(im)}},
            {'type': 'text', 'text': instruction},
        ]},
    ]
    payload = {'model': MODEL, 'messages': msgs, 'temperature': 0,
               'max_tokens': 512, 'stream': False}
    req = urllib.request.Request(
        BASE_URL.rstrip('/') + '/chat/completions',
        json.dumps(payload).encode(),
        {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=240) as resp:
        data = json.loads(resp.read())
    return data['choices'][0]['message']['content']


ACTION_PAT = re.compile(r"Thought:\s*(.+?)\s*Action:\s*(.+?)\s*$", re.S)
NATIVE_BOX = re.compile(
    r"<\|box\|>\s*\(?(\d+)\s*,\s*(\d+)\)?\s*,\s*\(?(\d+)\s*,\s*(\d+)\)?\s*<\|box\|>")


def parse_actions(text):
    """解析模型输出为动作列表；解析不出返回 []。"""
    m = ACTION_PAT.search(text.strip())
    if not m:
        return []
    thought, action = m.group(1).strip(), m.group(2).strip()
    kind = action.split('(', 1)[0].strip()
    args = {}
    for k, v in re.findall(r"(\w+)\s*=\s*'(.*?)'", action, re.S):
        args[k] = v
    for k, v in re.findall(r'(\w+)\s*=\s*"([^"]*)"', action, re.S):
        args.setdefault(k, v)
    known = {'click', 'left_double', 'right_single', 'type', 'hotkey',
             'scroll', 'wait', 'finished', 'call_user', 'drag'}
    if kind not in known:
        return []
    rename = {'left_double': 'double_click', 'right_single': 'right_click'}
    return [{'type': rename.get(kind, kind), 'thought': thought, **args}]


CROP = None   # --crop x,y,w,h：把截图裁到目标窗口再喂模型，坐标映射回全屏


def set_crop(spec):
    global CROP
    if not spec:
        CROP = None
        return None
    parts = [int(v) for v in spec.split(',')]
    if len(parts) != 4 or parts[2] <= 0 or parts[3] <= 0:
        raise ValueError('--crop 格式应为 x,y,w,h')
    CROP = tuple(parts)
    return CROP


def box_center(box):
    """模型 box（0-1000 千分比）→ Xvfb 像素中心点。

    支持三种格式：
      原生标记  <|box|>(x1,y1),(x2,y2)<|box|>
      方框      [x1, y1, x2, y2]
      点        (x, y)          # UI-TARS 常把 click 输出成点
    """
    nums = None
    m = NATIVE_BOX.search(box or '')
    if m:
        nums = [int(v) for v in m.groups()]
    else:
        m = re.search(r'\[([\d\s,.]+)\]', box or '')
        if m:
            nums = [int(float(v)) for v in re.findall(r'[\d.]+', m.group(1))]
        else:
            # 点格式：(900,572) —— 只有两个数，当作同一个点
            m = re.search(r'\(?(\d+)\s*,\s*(\d+)\)?', box or '')
            if m:
                a1, b1 = int(m.group(1)), int(m.group(2))
                nums = [a1, b1, a1, b1]
    if not nums or len(nums) != 4:
        return None
    x1, y1, x2, y2 = nums
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    # 千分比越界说明模型定位失败（实测见过输出 1352）：clamp 并标记，
    # 否则会换算出屏幕外或偏移几百像素的点击。
    clamped = any(v < 0 or v > 1000 for v in (x1, y1, x2, y2))
    x1, y1 = max(0, min(1000, x1)), max(0, min(1000, y1))
    x2, y2 = max(0, min(1000, x2)), max(0, min(1000, y2))
    if CROP:                       # 裁剪模式：千分比相对裁剪区，再映射回全屏
        ox, oy, cw, ch = CROP
        px = lambda v: ox + int(round(v / 1000.0 * cw))
        py = lambda v: oy + int(round(v / 1000.0 * ch))
    else:
        px = lambda v: int(round(v / 1000.0 * SCREEN_W))
        py = lambda v: int(round(v / 1000.0 * SCREEN_H))
    return ((px(x1) + px(x2)) // 2, (py(y1) + py(y2)) // 2, clamped)


def execute(act, dry_run=False):
    """执行单个动作；返回可读结果。坐标越界/干跑都不碰键鼠。"""
    t = act['type']
    if t in ('finished', 'call_user'):
        return 'FINISHED: ' + str(act.get('content', ''))
    if t == 'wait':
        time.sleep(1.0)
        return 'wait'
    if t in ('click', 'double_click', 'right_click', 'drag'):
        c = box_center(act.get('start_box', ''))
        if not c:
            return 'SKIP: 无有效坐标 ' + repr(act.get('start_box'))
        x, y, clamped = c
        if not (0 <= x < SCREEN_W and 0 <= y < SCREEN_H):
            return 'SKIP: 坐标越界 (%d,%d)' % (x, y)
        warn = ' [模型千分比越界已clamp]' if clamped else ''
        if dry_run:
            return 'DRYRUN %s (%d,%d)%s' % (t, x, y, warn)
        sh(['xdotool', 'mousemove', str(x), str(y)])
        time.sleep(0.15)
        if t == 'double_click':
            sh(['xdotool', 'click', '--repeat', '2', '--delay', '120', '1'])
        elif t == 'right_click':
            sh(['xdotool', 'click', '3'])
        else:
            sh(['xdotool', 'click', '1'])
        return '%s (%d,%d)%s' % (t, x, y, warn)
    if t == 'type':
        text = str(act.get('content', ''))
        if not text:
            return 'SKIP: 空文本'
        if dry_run:
            return 'DRYRUN type ' + text[:40]
        subprocess.run(['xsel', '--clipboard', '--input'], input=text.encode(),
                       env=ENV, timeout=10, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        sh(['xdotool', 'key', '--clearmodifiers', 'ctrl+v'])
        return 'type ' + text[:40]
    if t == 'hotkey':
        keys = str(act.get('key', '')).strip()
        if not keys:
            return 'SKIP: 空热键'
        if dry_run:
            return 'DRYRUN hotkey ' + keys
        sh(['xdotool', 'key', '--clearmodifiers', keys])
        return 'hotkey ' + keys
    if t == 'scroll':
        c = box_center(act.get('start_box', '')) or (SCREEN_W // 2, SCREEN_H // 2)
        direction = 'up' if str(act.get('direction', 'down')).startswith('up') else 'down'
        if dry_run:
            return 'DRYRUN scroll %s' % direction
        sh(['xdotool', 'mousemove', str(c[0]), str(c[1])])
        btn = '4' if direction == 'up' else '5'
        for _ in range(3):
            sh(['xdotool', 'click', btn])
            time.sleep(0.1)
        return 'scroll %s' % direction
    return 'SKIP: 未知动作 ' + t


def check_service():
    try:
        with urllib.request.urlopen(BASE_URL.rstrip('/') + '/models', timeout=10) as r:
            models = json.loads(r.read())
        return True, [m.get('id') for m in models.get('data', [])]
    except Exception as e:
        return False, '%s: %s' % (type(e).__name__, e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('task', nargs='?', help='给 UI-TARS 的任务描述')
    ap.add_argument('--max-steps', type=int, default=25)
    ap.add_argument('--dry-run', action='store_true', help='只打印动作不执行')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--crop', default=None, metavar='X,Y,W,H',
                    help='裁剪区域（绝对像素）：只把该区域喂给模型，坐标自动映射回全屏')
    args = ap.parse_args()
    try:
        set_crop(args.crop)
    except ValueError as e:
        print(json.dumps({'event': 'bad_crop', 'detail': str(e)}))
        return 2

    ok, info = check_service()
    if args.check:
        print(json.dumps({'service_up': ok, 'models': info, 'base_url': BASE_URL,
                          'display': DISPLAY}, ensure_ascii=False))
        return 0 if ok else 2
    if not ok:
        print(json.dumps({'event': 'service_down', 'detail': info,
                          'hint': '先跑 wsl/start-uitars-server.sh'},
                         ensure_ascii=False))
        return 2
    if not args.task:
        print(json.dumps({'event': 'no_task'}))
        return 2

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = LOG_DIR / time.strftime('%Y%m%d-%H%M%S')
    run_dir.mkdir(parents=True, exist_ok=True)
    instruction = args.task + (
        '\n\n规则：只做完成任务必需的操作；不要点击任何"发表/发送/发布/确认"类按钮；'
        '完成后用 finished(content=...) 说明结果。')

    for step in range(1, args.max_steps + 1):
        im = screenshot()
        im.save(run_dir / ('step%02d-before.png' % step))
        try:
            raw = ask_model(im, instruction)
        except Exception as e:
            print(json.dumps({'event': 'model_error', 'step': step,
                              'error': type(e).__name__, 'detail': str(e)[:200]},
                             ensure_ascii=False), flush=True)
            return 3
        acts = parse_actions(raw)
        print(json.dumps({'event': 'step', 'step': step, 'raw': raw[:600],
                          'actions': [{k: v for k, v in a.items() if k != 'thought'}
                                      for a in acts]}, ensure_ascii=False), flush=True)
        if not acts:
            print(json.dumps({'event': 'unparsable', 'step': step,
                              'raw': raw[:300]}, ensure_ascii=False), flush=True)
            return 4
        done = False
        for a in acts:
            result = execute(a, dry_run=args.dry_run)
            print(json.dumps({'event': 'action', 'step': step, 'type': a['type'],
                              'result': result,
                              'thought': (a.get('thought') or '')[:200]},
                             ensure_ascii=False), flush=True)
            if a['type'] in ('finished', 'call_user'):
                done = True
        if done:
            print(json.dumps({'event': 'run_done', 'steps': step,
                              'log_dir': str(run_dir)}, ensure_ascii=False))
            return 0
        time.sleep(0.8)
    print(json.dumps({'event': 'max_steps_reached', 'steps': args.max_steps,
                      'log_dir': str(run_dir)}, ensure_ascii=False))
    return 5


if __name__ == '__main__':
    raise SystemExit(main())
