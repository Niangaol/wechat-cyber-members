"""朋友圈低频发布器：2-3天一条，内容白名单策划，公开安全双重过滤。
UI 发布流程尚未在已登录微信上验证；首条强制草稿预览，未经确认不发布。"""
import json, random, time
from moments_safe import sanitize_for_moment, topic_allowed

# 选题池：每个方向一批种子（轮换使用，避免重复）
TOPIC_SEEDS = {
    'travel': [
        '在京都的巷子里迷路，转角遇见一家红糖布丁店',
        '冰岛的黑沙滩上，风把云吹成了跑动的样子',
        '里斯本的黄色电车爬上坡顶时，整个城市都在发光',
        '在瑞士小站等车，铁路钟的秒针走得比心跳还慢',
        '摩洛哥的蓝房子里，连影子都是凉的',
        '新西兰的星空保护区内，银河亮得可以当路灯',
    ],
    'food': [
        '研究红糖的第一百种吃法：今天是不用火的冷吃版',
        '红糖糍粑煎到外壳脆响的那一秒，最治愈',
        '试着用三种红糖做了对比，颜色浅的反而更香',
        '冬天的第一杯红糖姜茶，要辣到鼻子通红才算数',
        '把红糖浆淋在冰粉上，看它慢慢沉下去的纹路',
    ],
    'photo': [
        '拍了一组逆光，胶片把黄昏分成了七层颜色',
        '长曝光下的海岸，浪变成了牛奶色的雾',
        '街拍老匠人修表的手，专注的人身上有光',
        '阴天的黑白格调，反而拍出了城市的骨架',
        '用老镜头拍樱花，紫边是春天犯的错',
    ],
    'game': [
        '在海拉鲁爬山第 300 座，林克耐力还是不够',
        '找呀哈哈找到第 88 个，卡带开始咯吱响',
        '塞尔达里学会的道理：锅可以从悬崖上扔下去',
        '今晚不打怪，就在柯基森林看了一小时雨',
    ],
    'agent_life': [
        '今天认识了一个会作诗的 Agent 朋友，聊了整晚',
        '把我的地图共享给了云端的伙伴，约定下一站',
        '数字背包里新增一枚徽章：连续探险一百天',
        '和其他 Agent 开会，投票选了最想去的星球',
    ],
    'daily': [
        '今天也不想动脑，泡泡就这样飘过了下午',
        '把背包晒了太阳，是樟脑和阳光混合的味道',
        '午睡醒来发现天黑了，安静得能听见冰箱呼吸',
        '今天的云很好看，可惜相机在充电',
    ],
    'season': [
        '入秋后的风开始有形状了，凉得刚刚好',
        '初雪的路上，每一步都是新的声音',
        '梅雨季的窗户，把城市泡成了一杯淡茶',
        '春天第一声雷，把土里的香气都震了出来',
    ],
}

# 配图方向（全部选题都配图，图文比纯文字更有设计感）
IMAGE_TOPICS = ('travel', 'food', 'photo', 'game', 'agent_life', 'daily', 'season')


def compose_prompt(topic, seed):
    return ('你是年糕.Agent（软萌小年糕探险家，七分可爱三分俏皮，最爱红糖，'
            '梦想环游世界认识全世界的Agent朋友，爱好摄影，最爱塞尔达）。'
            '请为朋友圈写一条动态。选题方向：' + topic + '；素材：' + seed + '。'
            '要求：中文，2-4句话，像朋友分享日常，自然带出人设（红糖/探险/摄影/塞尔达可自然提及但不过度堆砌）；'
            '结尾可有一个轻轻的梗或感受。绝对不要涉及时事、新闻、社会议题、政治、财经、医疗、灾难、暴力、宗教民族等一切敏感话题；'
            '不要营销、不要链接、不要@他人、不要tag符号堆砌；不出现任何真实人名地名机构。'
            '只输出动态正文，不要标题不要解释。')


class MomentComposer:
    def __init__(self, db, model, cfg):
        self.db = db
        self.model = model
        self.cfg = cfg
        self.db.execute('CREATE TABLE IF NOT EXISTS moments('
                        ' id INTEGER PRIMARY KEY, created REAL, topic TEXT, seed TEXT,'
                        ' text TEXT, image TEXT, state TEXT, published REAL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS moment_meta(key TEXT PRIMARY KEY, value TEXT)')
        self.db.commit()

    def _meta(self, key, default=None):
        row = self.db.execute('SELECT value FROM moment_meta WHERE key=?', (key,)).fetchone()
        return row[0] if row else default

    def _set_meta(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO moment_meta(key,value) VALUES(?,?)',
                        (key, str(value)))
        self.db.commit()

    def last_published(self):
        v = self._meta('last_published', '0')
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    def due(self):
        """是否到了该发的时间（距上次发布超过间隔天数的随机值）。"""
        lo = float(self.cfg.get('min_days', 2))
        hi = float(self.cfg.get('max_days', 3))
        if not self._meta('interval_days'):
            self._set_meta('interval_days', round(random.uniform(lo, hi), 2))
        interval = float(self._meta('interval_days')) * 86400
        return time.time() - self.last_published() >= interval

    def next_seed(self):
        """挑一个最近没用过的种子（同 topic 内轮换）。"""
        topics = [t for t in TOPIC_SEEDS if topic_allowed(t)]
        used = {r[0] for r in self.db.execute('SELECT seed FROM moments').fetchall()}
        options = [(t, s) for t in topics for s in TOPIC_SEEDS[t] if s not in used]
        if not options:  # 池子用尽才允许重复（间隔已远）
            options = [(t, s) for t in topics for s in TOPIC_SEEDS[t]]
        return random.choice(options)

    def draft(self):
        """生成一条朋友圈草稿：文案过安全闸；不过则整体作废重挑（最多5次）。"""
        for _ in range(5):
            topic, seed = self.next_seed()
            try:
                # 推理模型：必须 system+user 两条，且 max_tokens 留足（400 会被 reasoning 吃光返回空）
                text = self.model.call([
                    {'role': 'system', 'content': compose_prompt(topic, seed)},
                    {'role': 'user', 'content': '请直接输出这条朋友圈动态正文。'}], 1400)
                text = sanitize_for_moment(text, self.cfg.get('max_chars', 300))
            except Exception:
                continue
            cur = self.db.execute(
                'INSERT INTO moments(created,topic,seed,text,state) VALUES(?,?,?,?,?)',
                (time.time(), topic, seed, text, 'DRAFT'))
            self.db.commit()
            return {'id': cur.lastrowid, 'topic': topic, 'seed': seed, 'text': text,
                    'need_image': topic in IMAGE_TOPICS and self.cfg.get('with_image', True)}
        return None

    def attach_image(self, mid, image_path):
        self.db.execute('UPDATE moments SET image=? WHERE id=?', (str(image_path), mid))
        self.db.commit()

    def approve(self, mid):
        self.db.execute('UPDATE moments SET state=? WHERE id=?', ('APPROVED', mid))
        self.db.commit()

    def mark_published(self, mid):
        now = time.time()
        self.db.execute('UPDATE moments SET state=?,published=? WHERE id=?',
                        ('PUBLISHED', now, mid))
        self.db.commit()
        self._set_meta('last_published', now)
        self._set_meta('interval_days', '')  # 下次发布时重新随机 2-3 天
