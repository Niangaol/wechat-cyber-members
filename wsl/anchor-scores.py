import json,sys
from pathlib import Path
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from wechat_ui import WeChatUI
from chat_anchors import anchor_path,text_mask
ui=WeChatUI(json.loads((ROOT/'config'/'resident.json').read_text()));im=ui.capture()
for name in ['很帅的年糕','Agent 聊天测试群']:
    t=np.asarray(text_mask(Image.open(anchor_path(name,'list'))))<140
    r=np.asarray(text_mask(im.crop((120,70,185,555))))<140
    hits=[]
    for y in range(r.shape[0]-t.shape[0]+1):
        w=r[y:y+t.shape[0]]
        score=2*np.logical_and(t,w).sum()/max(1,t.sum()+w.sum())
        hits.append((round(float(score),4),70+y))
    print(name,sorted(hits,reverse=True)[:5],flush=True)
