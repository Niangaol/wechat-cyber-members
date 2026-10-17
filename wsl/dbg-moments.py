"""离线验证朋友圈草稿：节奏（2-3天）、选题白名单、安全闸重挑、失败即作废。"""
import sys, os, json, sqlite3, time
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from moments import MomentComposer, TOPIC_SEEDS
from moments_safe import TOPIC_WHITELIST


class FakeModel:
    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = 0

    def call(self, messages, max_tokens=900):
        self.calls += 1
        return self.texts.pop(0) if self.texts else '今天的云像棉花糖'


def fresh(model, cfg=None):
    db = sqlite3.connect(":memory:")
    return MomentComposer(db, model, cfg or {'min_days': 2, 'max_days': 3,
                                             'max_chars': 300, 'with_image': True})


# 1) 节奏
m = fresh(FakeModel([]))
print("1a) 全新库 due:", m.due())
iv = float(m._meta('interval_days'))
print("    随机间隔天数:", iv, "(应在 2-3 之间:", 2 <= iv <= 3, ")")
d = m.draft()
m.mark_published(d['id'])
print("1b) 刚发过 due:", m.due(), "-> 应为 False")
m._set_meta('last_published', time.time() - 4 * 86400)
print("1c) 4 天后 due:", m.due(), "-> 应为 True")

# 2) 选题白名单
m2 = fresh(FakeModel([]), {'min_days': 0, 'max_days': 0, 'max_chars': 300})
topics = set()
for _ in range(30):
    t, s = m2.next_seed()
    topics.add(t)
print("2) 抽到的选题都在白名单内:", topics <= set(TOPIC_WHITELIST), "| 抽到:", sorted(topics))

# 3) 第一条文案不安全 → 重挑，最终落库的是安全的
m3 = fresh(FakeModel(['今天股市涨停了三支，推荐大家买入', '入秋的风开始有形状了']))
d3 = m3.draft()
print("3a) 首次不安全后落库文案:", d3['text'][:30], "| 模型调用次数:", m3.model.calls)

# 4) 五次都不安全 → 一条草稿都不建（fail-closed）
m4 = fresh(FakeModel(['股票涨停'] * 5))
d4 = m4.draft()
rows = m4.db.execute('SELECT count(*) FROM moments').fetchone()[0]
print("4) 五次都不安全 -> draft 返回:", d4, "| 草稿表行数:", rows)
