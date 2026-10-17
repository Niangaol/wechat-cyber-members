"""Live baseline test against a temporary bot ledger; no sending, models or input."""
import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from test_integration import make_resident,stop_patches
from wechat_ui import WeChatUI
cfg=json.loads((ROOT/'config'/'resident.json').read_text());cfg['debounce_seconds']=0
name='Agent 聊天测试群'
ui=WeChatUI(cfg);original=ui.run
def read_only(args,data=None,timeout=12):
    if args[0] in {'xdotool','xsel','xclip'}:raise RuntimeError('Input forbidden')
    return original(args,data,timeout)
ui.run=read_only
image=ui.verify_target(expected_chat=name)
r=make_resident(cfg)
try:
    started=time.perf_counter()
    first=r.observe_one(cfg,ui,None,name,image)
    second=r.observe_one(cfg,ui,None,name,ui.capture())
    ck='group:'+name
    result={'first_enqueued':first,'second_enqueued':second,'visible_baseline':len(r.baselines.get(ck,[])),
            'queue_depth':r.quota.depth(),'timeline_rows':len(r.memory.get_timeline(ck)),
            'historical_media_saved':(Path(r._tmp)/'media').exists(),
            'seconds':round(time.perf_counter()-started,3),'model_calls':0,'sent_messages':0}
    print(json.dumps(result,ensure_ascii=False),flush=True)
    assert not first and not second and result['visible_baseline'] >= 3 and result['queue_depth']==0
    assert result['timeline_rows']==0 and not result['historical_media_saved']
finally:
    r.db.close();stop_patches(r)
