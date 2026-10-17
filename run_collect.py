"""采集朋友圈新动态到互动收件箱（手动/低频跑，独立于主循环）。
用法：先登录+打开 Moments 窗口，然后 python3 run_collect.py"""
import json, sqlite3, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent/'src'))
from wechat_ui import WeChatUI, SafetyError
from moment_interact import MomentInbox, InteractionPipeline
from moments_collector import MomentsCollector
from multimodal import StepPlan

ROOT = Path(__file__).parent
CFG = json.loads((ROOT/'config'/'resident.json').read_text())


def main():
    ui = WeChatUI(CFG)
    inbox = MomentInbox(sqlite3.connect(str(Path.home()/'.local'/'state'/'wechat-bot'/'ledger.sqlite')))
    try:
        added = MomentsCollector(ui).collect(inbox, screens=3)
    except SafetyError as e:
        print('采集中止:', e); return
    print('新增动态:', added, '| 待处理:', inbox.pending_count())
    if inbox.pending_count() >= (CFG.get('interact') or {}).get('batch_size', 8):
        model = StepPlan(CFG)
        pipe = InteractionPipeline(model, CFG.get('interact'))
        stats = pipe.run_batch(inbox)
        print('决策完成:', stats)
        print('--- 待确认的互动（点赞+评论绑定）---')
        for mid, author, text, comment in inbox.approved():
            print('[%d] %s: %s' % (mid, author, text[:40]))
            print('    评论: %s' % comment)


if __name__ == '__main__':
    main()
