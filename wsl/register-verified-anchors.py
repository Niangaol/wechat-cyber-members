"""Register only previously visually verified screenshots; never infer an identity."""
import sys
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from chat_anchors import ROOT as ANCHORS, anchor_path, TITLE_BOX, text_mask
ANCHORS.mkdir(parents=True, exist_ok=True)
# These complete screenshots were inspected manually in this session.
specs = [('很帅的年糕','wsl-dm-open.png',226), ('Agent 聊天测试群','wsl-list-click.png',84)]
for name, source, row in specs:
    with Image.open(ROOT/source) as screen:
        window=screen.crop((129,30,1150,770)).convert('RGB')
        window.crop(TITLE_BOX).save(anchor_path(name,'title'))
        text_mask(window.crop((120,row,185,row+22))).save(anchor_path(name,'list'))
    print('registered verified anchor:',name)
