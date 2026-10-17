"""One real image-understanding draft. Uses shared quota; NEVER sends to WeChat."""
import json,sys,time,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from wechat_ui import WeChatUI
from visual_parse import extract_messages,classify
from multimodal import StepPlan
from resident import Resident
from output_safe import check_output
cfg=json.loads((ROOT/'config'/'resident.json').read_text())
ui=WeChatUI(cfg);original=ui.run
def read_only(args,data=None,timeout=12):
    if args[0] in {'xdotool','xsel','xclip'}:raise RuntimeError('Input forbidden')
    return original(args,data,timeout)
ui.run=read_only
start=time.perf_counter()
im=ui.verify_target(expected_chat='Agent 聊天测试群')
media=[m for m in extract_messages(im) if m['direction']=='in' and classify(im.crop(m['bbox']),'')=='image']
if not media:raise RuntimeError('No complete incoming image visible; no model call made')
model=StepPlan(cfg)
if not model.key():raise RuntimeError('Model credential unavailable; no request made')
r=Resident()
try:
    with tempfile.TemporaryDirectory() as td:
        path=Path(td)/'bubble.png';im.crop(media[-1]['bbox']).save(path)
        ctx={'chat_key':'group:Agent 聊天测试群','timeline':[{'direction':'in','kind':'image','text':'','image_path':str(path)}]}
        r.spend(model,cfg,2,'validation_image_draft')
        t=time.perf_counter()
        text=check_output(model.reply([{'direction':'in','kind':'text','text':'这是一次仅生成草稿的图片理解测试：用一句话描述图里角色的外观和画面布局，不要猜名字。'}],[],[],chat_context=ctx),cfg['reply_max_chars'])
        print(json.dumps({'draft':text,'model_seconds':round(time.perf_counter()-t,3),
                          'total_seconds':round(time.perf_counter()-start,3),'bbox':media[-1]['bbox'],
                          'quota_calls':1,'sent_messages':0,'safety_gate':'passed'},ensure_ascii=False),flush=True)
finally:
    r.db.close();r.lock.close()
