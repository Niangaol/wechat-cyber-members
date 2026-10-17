"""只读汇总自动好友监听及真实回复证据，不输出微信号或消息正文。"""
import json
import sqlite3
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from multimodal import STATE
from direct_registry import DirectRegistry
from resident import with_discovered,Resident

cfg=with_discovered(json.loads((ROOT/"config/resident.json").read_text()))
rows=DirectRegistry(STATE/"direct-friends.json").load()
status=json.loads((STATE/"status.json").read_text())
with sqlite3.connect("file:"+str(STATE/"ledger.sqlite")+"?mode=ro",uri=True) as db:
    replies=[]
    for name in rows:
        count,last=db.execute("SELECT count(*),max(created) FROM turns WHERE chat_key=? AND role='assistant'",("direct:"+name,)).fetchone()
        replies.append({"name":name,"reply_count":count,"last_reply_age_s":round(time.time()-last,1) if last else None})
print(json.dumps({"auto_discover":cfg.get("direct_auto_discover"),"friends":list(rows),"watching":Resident.watch_list(None,cfg),"state":status.get("state"),"heartbeat_age_s":round(time.time()-status.get("heartbeat",0),1),"queue_depth":status.get("queue_depth"),"poll_health":status.get("poll_health"),"replies":replies},ensure_ascii=False,indent=2))
