"""Read-only live title diagnostic: screenshot and local OCR, never sends input."""
import json
import sys
import time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from wechat_ui import WeChatUI, title_matches, normalize
cfg = json.loads((ROOT / 'config' / 'resident.json').read_text())
ui = WeChatUI(cfg)
t0 = time.perf_counter()
image = ui.capture()
region = image.crop((283, 20, 700, 61))
raw = ui.ocr(region, 7)
print(json.dumps({'window': ui.wid, 'size': image.size, 'title_ocr': raw,
                  'group_matches': [g for g in cfg.get('group_whitelist', []) if title_matches(g, raw, True)],
                  'seconds': round(time.perf_counter() - t0, 3)}, ensure_ascii=False))
region.save(ROOT / 'wsl-title-crop.png')
# Verify current-chat navigation without permitting any keyboard/clipboard/mouse command.
from chat_navigator import ChatNavigator
original_run = ui.run
commands = []
def read_only_run(args, data=None, timeout=12):
    commands.append(args[0])
    if args[0] in {'xdotool', 'xsel', 'xclip'}:
        raise RuntimeError('Diagnostic refuses input: ' + args[0])
    return original_run(args, data, timeout)
ui.run = read_only_run
matches = [g for g in cfg.get('group_whitelist', []) if title_matches(g, raw, True)]
if len(matches) == 1:
    start = time.perf_counter()
    ChatNavigator(ui).switch_to(matches[0])
    ui.verify_target(expected_chat=matches[0])
    print(json.dumps({'task_bound_target': matches[0], 'default_target_unchanged': ui.cfg.get('target_chat')}, ensure_ascii=False))
    print(json.dumps({'current_chat_fast_path': 'verified', 'input_commands': 0,
                      'seconds': round(time.perf_counter() - start, 3)}, ensure_ascii=False))
