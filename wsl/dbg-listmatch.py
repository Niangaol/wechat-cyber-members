"""调试：列表合并行 + 每一行的匹配结果（看 Deepseek 为什么找不到）。"""
import sys, json
from pathlib import Path
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from wechat_ui import WeChatUI                                   # noqa: E402
from chat_navigator import ocr_tsv, merge_list_lines, _line_matches, _list_match, find_list_anchor  # noqa: E402

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
img = ui.capture()
img.save(ROOT + "/shots/list-debug.png")
print("anchor for Deepseek:", find_list_anchor("Deepseek", img))
words = ocr_tsv(ui, img.crop((60, 60, 283, 555)))
n = "".join("Deepseek".split())
print("合并后的行：")
for cy, text, cx in merge_list_lines(words):
    t = "".join(ch for ch in str(text) if ch.isalnum())
    print("   y=%-4d cx=%-4d %-28r match=%-5s list_match=%s" % (60 + cy, cx, text,
          _line_matches(n, text), _list_match("Deepseek", text)))
