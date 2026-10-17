"""Live mouse-only navigation test. No typing, clipboard writes, model or sending."""
import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from wechat_ui import WeChatUI
from chat_navigator import ChatNavigator
cfg=json.loads((ROOT/'config'/'resident.json').read_text())
ui=WeChatUI(cfg)
original=ui.run
commands=[]
def mouse_only(args,data=None,timeout=12):
    if args[0] in {'xsel','xclip'}:raise RuntimeError('Clipboard forbidden')
    if args[0]=='xdotool':
        if args[1] not in {'mousemove','click'}:raise RuntimeError('Keyboard forbidden')
        commands.append(args)
    return original(args,data,timeout)
ui.run=mouse_only
nav=ChatNavigator(ui)
for i,name in enumerate(['Agent 聊天测试群','很帅的年糕','Agent 聊天测试群']):
    t=time.perf_counter()
    image=nav.switch_to(name)
    ui.verify_target(image,expected_chat=name)
    image.save(ROOT/('navigation-'+str(i)+'.png'))
    print(json.dumps({'target':name,'verified':True,'seconds':round(time.perf_counter()-t,3)},ensure_ascii=False),flush=True)
print(json.dumps({'input_actions':commands,'text_input':False,'sent_messages':0}),flush=True)
