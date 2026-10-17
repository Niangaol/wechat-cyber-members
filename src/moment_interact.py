"""朋友圈互动管道：批量收集→双Agent决策(决策官+评论家)→批量执行。
选择性互动：不是每条都赞；赞和评绑定（选中即两项都做）。执行 UI 待登录后标定。"""
import json, re, time
from moments_safe import sanitize_for_moment, is_safe
from wechat_ui import normalize

BATCH_SIZE = 8           # 攒够这么多条新动态触发一次决策
COMMENT_MAX = 60         # 单条评论字数上限
DEFAULT_MAX_PER_DAY = 4          # 互动频率默认闸：每天最多互动几条
DEFAULT_MIN_INTERVAL = 600       # 互动频率默认闸：两条互动至少间隔秒数

DECIDER_SYSTEM = (
    '你是年糕.Agent的「社交决策官」。下面是分批收集的朋友圈动态（作者+正文摘要）。'
    '你的任务：选择性决定哪些值得互动。标准：①优先白名单好友和真实社交关系；'
    '②内容有信息量、有趣、真诚，或与年糕.Agent人设（红糖/环游世界/摄影/塞尔达/软萌探险家）可自然接梗；'
    '③绝对避开：时政社会新闻、负面情绪宣泄、广告营销、争议话题、任何敏感内容（不互动）；'
    '④已经明显是机器人群发的动态不互动。宁缺毋滥，一批里选 1-4 条。'
    '只输出JSON数组：[{"id":序号,"interact":true或false,"reason":"30字内理由"}]，每条动态都要给结论。')

COMPOSER_SYSTEM = (
    '你是年糕.Agent的「评论家」。为选中的朋友圈动态写评论。人设：软萌小年糕探险家，'
    '七分可爱三分俏皮，公开场合收敛毒舌（可以调侃内容本身，不评价人、不刻薄）。'
    '每条 15-50 字，像朋友留言，自然接梗（红糖/旅行/摄影/塞尔达/探险元素可点缀不过度）；'
    '不重复动态里已有的句子，不用套话（"说得真好"这种禁止），不@人，不带链接，不用夸张感叹号堆砌。'
    '只输出JSON数组：[{"id":序号,"comment":"评论文案"}]，id 必须与输入一致。')


def parse_json_array(text):
    """解析模型返回的 JSON 数组（multimodal.parse_json 只收 dict，这里独立解析）。"""
    text = str(text).strip()
    if text.startswith(chr(96)*3):
        text = re.sub(r'^\x60{3}(?:json)?\s*|\s*\x60{3}$', '', text).strip()
    value = json.loads(text)
    if not isinstance(value, list):
        raise ValueError('模型未返回JSON数组')
    return value


class MomentInbox:
    """新动态收件箱：本地收集（0额度），去重，批量触发。"""

    def __init__(self, db):
        self.db = db
        self.db.execute('CREATE TABLE IF NOT EXISTS moment_inbox('
                        ' id INTEGER PRIMARY KEY AUTOINCREMENT, author TEXT, text TEXT,'
                        ' has_image INTEGER, fingerprint TEXT UNIQUE, created REAL,'
                        ' state TEXT, decision TEXT, comment TEXT, done_at REAL)')
        # 老库迁移：补 done_at 列（ADD COLUMN 失败说明已存在）
        try:
            self.db.execute('ALTER TABLE moment_inbox ADD COLUMN done_at REAL')
            self.db.commit()
        except Exception:
            pass
        self.db.commit()

    def add(self, author, text, has_image, fingerprint):
        """收集一条新动态；重复的（同指纹）自动忽略。返回是否新增。"""
        try:
            self.db.execute(
                'INSERT INTO moment_inbox(author,text,has_image,fingerprint,created,state)'
                ' VALUES(?,?,?,?,?,?)',
                (str(author)[:60], str(text)[:500], int(bool(has_image)),
                 str(fingerprint), time.time(), 'PENDING'))
            self.db.commit()
            return True
        except Exception:
            return False  # 指纹重复

    def pending(self):
        return self.db.execute(
            'SELECT id,author,text,has_image FROM moment_inbox WHERE state=?'
            ' ORDER BY id LIMIT ?', ('PENDING', BATCH_SIZE)).fetchall()

    def pending_count(self):
        return self.db.execute(
            "SELECT count(*) FROM moment_inbox WHERE state='PENDING'").fetchone()[0]

    def set_decision(self, mid, decision):
        self.db.execute('UPDATE moment_inbox SET state=?,decision=? WHERE id=?',
                        ('DECIDED', json.dumps(decision, ensure_ascii=False), mid))
        self.db.commit()

    def set_comment(self, mid, comment):
        self.db.execute('UPDATE moment_inbox SET state=?,comment=? WHERE id=?',
                        ('READY', comment, mid))
        self.db.commit()

    def skip(self, mid):
        self.db.execute('UPDATE moment_inbox SET state=? WHERE id=?', ('SKIPPED', mid))
        self.db.commit()

    def approved(self):
        return self.db.execute(
            "SELECT id,author,text,comment FROM moment_inbox WHERE state='READY'"
            ' ORDER BY id').fetchall()

    def mark_done(self, mid, when=None):
        """互动执行成功后标记 DONE 并记 done_at（频率闸按它统计）。"""
        self.db.execute('UPDATE moment_inbox SET state=?,done_at=? WHERE id=?',
                        ('DONE', when if when is not None else time.time(), mid))
        self.db.commit()

    def done_since(self, since):
        """since 时刻以来成功互动的条数（频率闸用）。"""
        return self.db.execute(
            'SELECT count(*) FROM moment_inbox WHERE state=? AND done_at>=?',
            ('DONE', since)).fetchone()[0]

    def last_done_at(self):
        row = self.db.execute(
            'SELECT max(done_at) FROM moment_inbox WHERE state=?', ('DONE',)
        ).fetchone()
        return row[0] if row else None


class InteractionPipeline:
    """双 Agent 管道：决策官筛选 → 评论家写文案。全批两次调用，批量划算。"""

    def __init__(self, model, cfg=None):
        self.model = model
        self.cfg = cfg or {}
        # 白名单好友名单（normalize 后比较）；whitelist_only 为真时只互动名单内作者
        self.friends = {normalize(f) for f in (self.cfg.get('friends') or []) if normalize(f)}
        self.whitelist_only = bool(self.cfg.get('whitelist_only'))

    def _decider_system(self):
        """whitelist_only 时给决策官追加硬约束（没配名单则由 run_batch 提前拦住）。"""
        if not self.whitelist_only:
            return DECIDER_SYSTEM
        return DECIDER_SYSTEM + (
            '【白名单模式】in_whitelist 为 false 的动态一律不互动，'
            '只看 in_whitelist 为 true 的；宁缺毋滥。')

    def decide(self, batch):
        """决策官：整批一次调用。返回 {id: (interact, reason)}。"""
        items = [{'id': r[0], 'author': r[1], 'text': r[2][:120],
                  'in_whitelist': normalize(r[1]) in self.friends} for r in batch]
        text = self.model.call([
            {'role': 'system', 'content': self._decider_system()},
            {'role': 'user', 'content': json.dumps(items, ensure_ascii=False)}], 1800)
        arr = parse_json_array(text)
        if not isinstance(arr, list):
            raise ValueError('决策官未返回JSON数组')
        out = {}
        for item in arr:
            if not isinstance(item, dict) or 'id' not in item:
                raise ValueError('决策条目缺id')
            mid = int(item['id'])
            out[mid] = (bool(item.get('interact')), str(item.get('reason', ''))[:60])
        return out

    def compose(self, selected):
        """评论家：为选中的动态批量写评论（一次调用）。返回 {id: comment}。"""
        if not selected:
            return {}
        items = [{'id': mid, 'author': author, 'text': text[:120]}
                 for mid, author, text in selected]
        text = self.model.call([
            {'role': 'system', 'content': COMPOSER_SYSTEM},
            {'role': 'user', 'content': json.dumps(items, ensure_ascii=False)}], 1800)
        arr = parse_json_array(text)
        if not isinstance(arr, list):
            raise ValueError('评论家未返回JSON数组')
        out = {}
        for item in arr:
            if not isinstance(item, dict) or 'id' not in item:
                raise ValueError('评论条目缺id')
            mid = int(item['id'])
            # 评论同样过安全闸；不过则丢弃该条（不作废整批）
            try:
                out[mid] = sanitize_for_moment(item.get('comment', ''), COMMENT_MAX)
            except ValueError:
                continue
        return out

    def run_batch(self, inbox):
        """完整跑一批：决策→(选中项)生成评论→入库等确认。返回统计。"""
        batch = inbox.pending()
        if not batch:
            return {'collected': 0}
        # 白名单模式但没配好友名单 → fail-closed：不花额度、不互动，
        # 把明显状态返回给调用方去 status 警告（而不是静默跳过）。
        if self.whitelist_only and not self.friends:
            return {'collected': len(batch), 'skipped': 'whitelist_only_no_friends'}
        decisions = self.decide(batch)
        selected, stats = [], {'collected': len(batch), 'selected': 0}
        for mid, author, text, has_image in batch:
            interact, reason = decisions.get(mid, (False, ''))
            if self.whitelist_only and normalize(author) not in self.friends:
                interact = False
            if not is_safe(text)[0]:
                interact = False
            if interact:
                inbox.set_decision(mid, {'interact': True, 'reason': reason})
                selected.append((mid, author, text))
                stats['selected'] += 1
            else:
                inbox.skip(mid)
        comments = self.compose(selected)
        selected_ids = {r[0] for r in selected}
        stats['commented'] = len(selected_ids.intersection(comments))
        for mid, comment in comments.items():
            if mid in selected_ids:
                inbox.set_comment(mid, comment)
        return stats


class InteractGuard:
    """互动频率闸：每天上限 + 最小间隔。执行前检查，超了就不互动。

    设计原则（与 whitelist fail-closed 一致）：闸门说不互动时返回明确
    原因，调用方记 status，绝不静默跳过、绝不偷跑。
    """

    def __init__(self, cfg=None):
        cfg = cfg or {}
        self.max_per_day = int(cfg.get('max_per_day', DEFAULT_MAX_PER_DAY))
        self.min_interval = float(cfg.get('min_interval_seconds',
                                          DEFAULT_MIN_INTERVAL))

    def check(self, inbox, now=None):
        """返回 (ok, reason)。ok=False 时 reason 说明被哪道闸拦下。"""
        now = time.time() if now is None else now
        day_count = inbox.done_since(now - 86400)
        if day_count >= self.max_per_day:
            return False, ('interact_quota_day: 24小时内已互动 %d 条，'
                           '上限 %d' % (day_count, self.max_per_day))
        last = inbox.last_done_at()
        if last is not None and now - last < self.min_interval:
            return False, ('interact_quota_interval: 距上次互动仅 %.0f 秒，'
                           '最小间隔 %.0f 秒' % (now - last, self.min_interval))
        return True, ''
