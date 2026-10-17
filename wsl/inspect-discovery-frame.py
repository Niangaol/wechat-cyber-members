"""离线分析好友发现时采集的截图，不操作微信。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from PIL import Image
from visual_parse import avatar_rows, extract_messages
img = Image.open(Path(__file__).resolve().parents[1] / "shots/discovery-before.png").convert("RGB")
for x in (305,340,355,370,961,926):
    print(x, avatar_rows(img, x))
try:
    print("messages", len(extract_messages(img)))
except ValueError as exc:
    print("parse_error", str(exc))
