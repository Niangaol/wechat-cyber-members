"""离线验证"点赞评论"（互动）管道的安全闸：不碰 UI、不联网，用假模型。"""
import sys, os, json, sqlite3, time
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from moment_interact import MomentInbox, InteractionPipeline, InteractGuard


class FakeModel:
    def __init__(self, decisions, comments):
        self.decisions = decisions
        self.comments = comments
        self.calls = []

    def call(self, messages, max_tokens=900):
        system = str(messages[0].get('content', '')) if messages else ''
        self.calls.append('decide' if '决策' in system else 'compose')
        body = self.decisions if '决策' in system else self.comments
        return json.dumps(body, ensure_ascii=False)


def fresh_inbox():
    return MomentInbox(sqlite3.connect(":memory:"))


cfg = {'whitelist_only': True, 'friends': [], 'comment_max': 60}

# 1) 白名单模式但没配名单 → fail-closed、零模型调用
inbox = fresh_inbox()
inbox.add('很帅的年糕', '今天拍了张很好看的云', False, 'fp1')
m1 = FakeModel([{'id': 1, 'interact': True, 'reason': '好友'}], [{'id': 1, 'comment': '云真好看'}])
print("1) 没配白名单:", InteractionPipeline(m1, cfg).run_batch(inbox), "| 模型调用:", m1.calls)

# 2) 白名单内 → 决策+评论入库等确认（不执行），调用恰好 2 次
cfg2 = dict(cfg, friends=['很帅的年糕'])
inbox2 = fresh_inbox()
inbox2.add('很帅的年糕', '今天拍了张很好看的云', False, 'fp2')
m2 = FakeModel([{'id': 1, 'interact': True, 'reason': '好友日常'}],
               [{'id': 1, 'comment': '云真好看，像棉花糖'}])
print("2) 白名单内:", InteractionPipeline(m2, cfg2).run_batch(inbox2), "| 模型调用:", m2.calls)
print("   待确认:", inbox2.pending(), "| 已确认:", inbox2.approved())

# 3) 白名单外，决策官说互动也要被强制拦下
inbox3 = fresh_inbox()
inbox3.add('某个陌生人', '我也来发一条', False, 'fp3')
m3 = FakeModel([{'id': 1, 'interact': True, 'reason': '看起来不错'}], [])
print("3) 白名单外:", InteractionPipeline(m3, cfg2).run_batch(inbox3), "| 待确认:", len(inbox3.pending()))

# 4) 评论过不了安全闸 → 丢该条，不作废整批
inbox4 = fresh_inbox()
inbox4.add('很帅的年糕', '随便聊聊', False, 'fp4')
m4 = FakeModel([{'id': 1, 'interact': True, 'reason': '好友'}],
               [{'id': 1, 'comment': '加我微信 13800000000 聊'}])
print("4) 不安全评论:", InteractionPipeline(m4, cfg2).run_batch(inbox4), "| 落库评论:",
      [r for r in inbox4.db.execute('SELECT id, comment FROM moment_inbox')])

# 5) 频率闸
g = InteractGuard({'max_per_day': 3, 'min_interval_seconds': 600})
inbox5 = fresh_inbox()
for i in range(1, 6):
    inbox5.add('很帅的年糕', '第 %d 条动态' % i, False, 'fp%d' % i)
print("5a) 干净:", g.check(inbox5, now=1000000))
inbox5.mark_done(1, when=999900)                      # 100 秒前刚互动过（< 600s）
print("5b) 刚互动过(最小间隔 600s):", g.check(inbox5, now=1000000))
for i, t in ((2, 1000000 - 4000), (3, 1000000 - 3000), (4, 1000000 - 2000)):
    inbox5.mark_done(i, when=t)
print("5c) 一天 4 次(上限 3):", g.check(inbox5, now=1000000))
