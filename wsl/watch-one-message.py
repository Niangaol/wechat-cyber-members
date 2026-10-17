"""180-second live inbox-only test. Temporary ledger, no models, no sending, no input."""
import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from test_integration import make_resident,stop_patches
from wechat_ui import WeChatUI
cfg=json.loads((ROOT/'config'/'resident.json').read_text())
name='Agent 聊天测试群';ck='group:'+name
ui=WeChatUI(cfg);original=ui.run

def read_only(args,data=None,timeout=12):
    if args[0] in {'xdotool','xsel','xclip'}:raise RuntimeError('Input forbidden')
    return original(args,data,timeout)
ui.run=read_only
r=make_resident(cfg);r.feed.refresh=lambda:None
try:
    image=ui.verify_target(expected_chat=name)
    r.observe_one(cfg,ui,None,name,image)
    if ck not in r.baselines:raise RuntimeError('Baseline not stable; no watch started')
    print(json.dumps({'state':'baseline_ready','seconds_to_send':180,'visible_baseline':len(r.baselines[ck]),'no_sending':True}),flush=True)
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        time.sleep(2)
        image=ui.verify_target(expected_chat=name)
        started=time.perf_counter()
        if r.observe_one(cfg,ui,None,name,image):
            row=r.quota.peek();task=json.loads(row[-1])
            timeline=r.memory.get_timeline(ck)
            result={'state':'new_message_enqueued','queue_depth':r.quota.depth(),'priority':row[2],
                    'kinds':[m['kind'] for m in task['messages']],
                    'text_chars':[len(m.get('text','')) for m in task['messages']],
                    'timeline_rows':len(timeline),'other_chat_rows':len(r.memory.get_timeline('direct:很帅的年糕')),
                    'observation_seconds':round(time.perf_counter()-started,3),
                    'model_calls':0,'sent_messages':0}
            print(json.dumps(result,ensure_ascii=False),flush=True)
            (ROOT/'wsl'/'live-inbox-evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
            break
    else:print(json.dumps({'state':'watch_expired','model_calls':0,'sent_messages':0}),flush=True)
finally:r.db.close();stop_patches(r)
