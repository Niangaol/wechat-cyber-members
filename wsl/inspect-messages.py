"""Read-only live message parser diagnostic. Never enqueue, send or call models."""
import json,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from wechat_ui import WeChatUI
from chat_navigator import ocr_tsv
from visual_parse import extract_messages, classify
ui=WeChatUI(json.loads((ROOT/'config'/'resident.json').read_text()))
im=ui.capture()
t=time.perf_counter()
words=ocr_tsv(ui,im)
try:
    bubbles=extract_messages(im)
    for b in bubbles:
        x1,y1,x2,y2=b['bbox']
        text=' '.join(s for s,x,y,w,h in words if x1-4<=x+w//2<=x2+4 and y1-4<=y+h//2<=y2+4)
        b['text']=text
        b['kind']=classify(im.crop(b['bbox']),text)
    print(json.dumps({'seconds':round(time.perf_counter()-t,3),'messages':bubbles},ensure_ascii=False),flush=True)
except Exception as e:
    print(json.dumps({'error':type(e).__name__,'reason':str(e)},ensure_ascii=False),flush=True)
    raise
