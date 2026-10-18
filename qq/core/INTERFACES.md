# QQ 接入接口约定 v1（owner: lead；改接口先发消息给 lead，不要各自发明）

## 0. 文件所有权（各自只写自己的范围）
- `qq/core/**`（除本文件与 __init__.py）→ qq-core
- `qq/bot.py`、`qq/plugins/**`、`qq/config/qq.example.json`、`qq/requirements.txt` → qq-nonebot
- `wsl/qq-*.sh|.py|.service`、`docs/QQ.md`、`README.md` 的 QQ 段落 → qq-deploy
- `src/**` → 只属于 lead；需要共享模块改动就发消息，不要自己改
- 测试文件：`test_qq_core*.py`（qq-core）、`test_qq_plugin*.py`（qq-nonebot）、`test_qq_deploy*.py`（qq-deploy）

## 1. 硬约束
- `qq/core/**` 只 import 标准库 + PIL + `src/` 模块；**禁止** import nonebot / asyncio bot；全部是同步阻塞代码。
- `src/` 进 sys.path 只允许在 `qq/core/__init__.py`（lead 已写好）。其它模块直接 `import memory` 这类裸导入。
- 注释、日志、文档全中文。QQ 号/token/密钥不进仓库（示例配置写占位符）。
- 测试不出网、不连真实 QQ/微信、不读生产库；用 `:memory:` sqlite 或 tmpdir。
- 生产状态目录 `~/.local/state/qq-bot/`（由 cfg['state_dir'] 覆盖）：db、media、STOP、status.json 都在这里。

## 2. envelope.py
```python
@dataclass
class QEvent:
    self_id: str; chat_type: str   # 'private'|'group'
    chat_id: str; sender_id: str; sender_name: str
    message_id: str; time: float; at_me: bool; at_all: bool
    text: str; images: list[dict]; segments: list[dict]; raw: dict
    # 属性：chat_key -> 'qq:<self_id>:<chat_type>:<chat_id>'
    # 属性：dedupe_key -> '<self_id>:<chat_type>:<chat_id>:<message_id>'
    # 属性：kind -> chat_type（给 memory.note_messages(kind=...) 用）

def from_onebot_event(payload: dict) -> QEvent | None
```
- 只接受 `post_type=='message'` 且 `message_type in ('private','group')`；其余返回 None（notice/request/meta 一律丢弃）。
- 自身消息（`sender.user_id == self_id`）返回 None。
- `message` 段支持 array（list[dict]）与 string（最小 CQ 解析），**string 也必须解出纯文本**，绝不把 CQ 码塞进 text。
- `text` = 所有 text 段拼接后 strip；`at_me` = 存在 `{'type':'at','data':{'qq': self_id}}`；`at_all` = qq=='all'（不算 at_me）。
- `images` = image 段 → `{'url': ..., 'file': ...}`（只记录，不下载）。

## 3. policy.py
```python
@dataclass
class Decision: action: str   # 'reply'|'context_only'|'ignore'
                 priority: int; reason: str

def decide(event, cfg, *, now, queue_depth, last_reply_at, group_plain_times) -> Decision
```
判定顺序（fail-closed；配置缺失/类型不对 → ignore）：
1. chat_type 非 private/group → ignore。
2. private：`direct_policy`（默认 blacklist）——blacklist 时 chat_id 在 `direct_blacklist` 里 → ignore；whitelist 时不在 `direct_whitelist` → ignore；否则 reply/priority=`PRIORITY_DIRECT`。
3. group：`groups` 是 **group_id 为键** 的白名单；没登记 → ignore。
   - `at_me` → reply/`PRIORITY_GROUP_AT`；
   - 文本命中 `mention_aliases`，或 `last_reply_at` 在 `followup_window_s`（默认 60）内且消息含问号/疑问词 → reply/`PRIORITY_GROUP_AT`；
   - 否则按该群 `plain_mode`：`at_only`（默认）→ context_only；`selective` → context_only；`idle` → 仅当 `queue_depth==0` 且 `plain_cooldown_s`（默认 120）已过 → reply/`PRIORITY_GROUP_PLAIN`，否则 context_only；`all` → reply/`PRIORITY_GROUP_PLAIN`。
   - `plain_per_hour`（默认 6，0=不限）：`group_plain_times` 一小时内条数到顶 → context_only。
4. 频率闸：`now - last_reply_at < min_reply_seconds`（默认 3）→ context_only（reason='min_reply_seconds'），消息照记时间线。
5. `max_replies_per_hour`（默认 30，0=不限）在 worker 侧用 turns 表计数，同样退回 context_only。
优先级常量直接 `from quota import PRIORITY_GROUP_AT, PRIORITY_DIRECT, PRIORITY_GROUP_PLAIN`。

## 4. bridge.py
```python
@dataclass
class SendResult: ok: bool; unknown: bool; error: str; message_id: str

class Sender(ABC):
    def send_text(self, event, text) -> SendResult
    def send_image(self, event, path) -> SendResult
    def self_id(self) -> str
    def online(self) -> bool
```
- 只能发到 event 自己的会话（接口不接受任意目标，防止被提示注入改成发别人）。
- `unknown=True` 表示"发出去没有确认"（超时/断线）→ worker 记 unknown、**不重发**。

## 5. media.py
```python
def fetch_image(url, dest_dir, *, max_bytes=10*1024*1024, timeout_s=15) -> Path | None
def within_event_limit(event, max_images=2) -> list[str]   # 取前 N 个 url
```
- 只允许 http/https、无凭据、端口 80/443；DNS 解析后所有地址必须 is_global，连接固定到该 IP（照抄 src/web_reader.py 的写法防重绑定）；拒绝私网/本机/混合解析。
- 校验魔数 PNG/JPEG/GIF/WEBP + PIL `verify()`，像素上限 20MP；落盘 `dest_dir/<sha256 前16>.<ext>`，权限 600。
- 任何失败返回 None 并写日志，**绝不抛异常给调用方**（没图就当纯文字消息回）。

## 6. store.py
```python
class Store:
    def __init__(self, db_path)                      # WAL；建表 inbound/send_log/targets
    def seen(self, dedupe_key) -> bool               # 首次 True 并登记，重复 False
    def remember_target(self, chat_key, chat_type, chat_id)
    def target_of(self, chat_key) -> tuple | None
    def record_send(self, chat_key, kind, state, detail='')   # kind: text|image；state: ok|failed|unknown
    def last_send(self, chat_key, kind=None) -> dict | None
    def stats(self) -> dict
```

## 7. service.py / worker.py
```python
class QQService:
    def __init__(self, cfg, root: Path, sender: Sender, db_path=None, clock=time.time)
    def start(self) -> None          # 起单条 daemon 线程（owner thread）
    def stop(self, timeout=5.0) -> None
    def submit(self, event) -> bool  # 线程安全入队；满/过期拒绝并计数
    def status(self) -> dict
```
- `start()` 之后所有 sqlite / 模型 / 网络下载都在 owner 线程里做；`submit()` 只入队。
- 队列复用 `src/quota.py::Quota`（QQ 自己的 db）：`enqueue(chat_key, priority, payload)` 自带同会话合并，worker 用 `claim()/finish()/depth()`。
- 处理循环：STOP 检查（`state_dir/'STOP'` 存在就停手不发送）→ `memory.note_messages` + `add_timeline` → 下载图片 → 生成回复 → 发送 → `record_turn`。
- 生成：`StepPlan(cfg, db, state_dir=state_dir)` + `model.reply(fresh, ctx['recent_turns'], sources, chat_context=ctx, hot_items=hot, search_fn=search_fn)`，然后 `check_output(reply, cfg['reply_max_chars'])`。搜索走受限工具链，每次回复最多一次。
- 生图：只在明确要图时；`imagegen.generate(prompt, state_dir=state_dir, credentials_file=cfg['image_generation']['credentials_file'])`，每会话每小时 ≤3 张、每次 ≤1 张；文字已发成功而图片失败时**不重发文字**。
- 额度：`Quota.check(cfg['limits'])` + `consume(priority)`（语义同微信，但独立 db）。
- `status()` 返回 `{'state','heartbeat','queue_depth','self_id','online','last_event_at','last_send_ok_at','last_error','sent_1h','stop'}`，并原子写 `state_dir/status.json`。

## 8. NoneBot 侧（qq-nonebot）
- `qq/bot.py`：`nonebot.init(...)` + 启动钩子里拿 running loop → 构造 `NoneBotSender`（`asyncio.run_coroutine_threadsafe`）与 `QQService` → `nonebot.load_plugin('qq.plugins.qq_chat')`。
- `qq/plugins/qq_chat.py`：`on_message(priority=...) / block=False`；只做 `from_onebot_event(event.dict())` → `service.submit()`，**永不 await 模型**。
- 发送：`bot.call_api('send_msg', message_type='private', user_id=..., message=[...])` / group 用 `group_id`；图片走 `{'type':'image','data':{'file':'base64://...'}}`（本地字节，不用远端 URL）。
- 异常/超时 → `SendResult(ok=False, unknown=True)`。

## 9. 配置 schema（qq.json，冻结版；qq-nonebot 的示例文件必须逐字对得上）

```jsonc
{
  "_说明": "QQ 侧配置。密钥/token 不进仓库；QQ 号只在本地文件里出现。",
  "self_id": "",                       // 可选：绑定账号。空 = 登录后自动绑定并写回 state_dir/self_id.txt
  "state_dir": "~/.local/state/qq-bot", // 支持 ~；程序内 expanduser
  "auto_send": false,                  // 总闸：false = 只记录/入队不发送（首次部署默认关，验收后再开）
  "onebot": {                          // NoneBot 反向 WS 监听（NapCat 作为客户端连过来）
    "host": "127.0.0.1",
    "port": 18080,
    "path": "/onebot/v11/ws",
    "token": "",                       // 为空时看 token_env；两者都空 → bot 拒绝启动（fail-closed）
    "token_env": "QQ_BOT_ONEBOT_TOKEN" // 环境变量优先于 token 字段
  },
  "napcat": { "webui_host": "127.0.0.1", "webui_port": 6099 },  // 只给运维脚本比对，程序不读
  "direct_policy": "blacklist",        // blacklist | whitelist
  "direct_blacklist": [],
  "direct_whitelist": [],
  "group_policy": "whitelist",         // 固定 whitelist：groups 里没登记的群一律不接
  "groups": {                          // 键 = 群号（字符串）
    "123456789": { "plain_mode": "at_only", "plain_cooldown_s": 120,
                   "plain_per_hour": 6, "followup_window_s": 60 }
  },
  "mention_aliases": ["年糕Agent", "年糕"],
  "limits": { "window_5h": 100, "window_1d": 500 },
  "min_reply_seconds": 3,
  "max_replies_per_hour": 30,
  "max_pending": 200,
  "task_ttl_seconds": 600,
  "reply_max_chars": 200,
  "reply_image_limit": 2,
  "image_generation": { "enabled": false, "max_per_hour": 3,
    "credentials_file": "/home/niangao/.local/state/wechat-bot/credentials.json" },
  "media": { "max_bytes": 10485760, "timeout_s": 15, "max_images": 2, "keep_days": 14 },
  "model": { "enabled": true, "base_url": "https://...", "model": "...",
             "api_key_env": "STEP_PLAN_API_KEY",
             "credential_file": "/home/niangao/.local/state/wechat-bot/credentials.json",
             "credential_key": "step_plan_api_key", "timeout": 90, "reasoning_effort": "low" },
  "web_search": { "enabled": true,
    "credential_file": "/home/niangao/.local/state/wechat-bot/credentials.json" },
  "links": { "enabled": true, "max_urls": 2, "max_bytes": 250000, "max_chars": 9000,
             "timeout": 10, "total_budget_seconds": 12 },
  "hot_feed": { "enabled": false, "refresh_seconds": 300 }   // 默认关：第三方慢源，要热榜自己开
}
```

优先级与校验（qq-core 的 config.py 必须实现，测试要覆盖）：
1. token：`os.environ[onebot.token_env]` 优先，其次 `onebot.token`；两者都空 → 启动即抛异常（绝不无鉴权开监听）。
2. `groups` 必须是 dict（键是数字字符串）；空 dict 合法（=谁都不接）。
3. `direct_policy` 只接受 blacklist/whitelist，其它值 → 当 blacklist 且写 warn（fail-closed：宁可少接）。
4. `state_dir` 用 `Path(...).expanduser()`；创建时 chmod 700，db/media/STOP/status.json 都在里面。
5. 未知字段忽略并 warn，不因为多写一个键就崩。

NapCat 侧配置（部署脚本按此比对，找不到就 SKIP 不要 FAIL）：
- 候选路径按顺序找 `onebot11_<QQ号>.json` / `webui.json`：`~/Napcat/opt/QQ/resources/app/app_launcher/napcat/config/`、
  `/opt/QQ/resources/app/app_launcher/napcat/config/`、`~/.config/QQ/NapCat/config/`。
- 比对项：websocketClients[0].url 的端口/路径 == `onebot.port`+`onebot.path`；其 token == 生效 token（只比哈希/长度，不打印明文）。
- WebUI：host 必须是 127.0.0.1（0.0.0.0 → FAIL 并提示改），port 默认 6099。
## 7.1 契约 v1.1 增补（lead，2026-10-18）：线程模型与两条能力

**线程模型（对 §7 的修订）**：QQService.start() 起 **worker + status 心跳 + hot 热榜** 三条 daemon 线程。
- worker（owner）：唯一处理队列 / 调模型 / 下载图片 / 发送的线程；
- status：独立写 status.json 心跳——owner 一次模型调用十几秒、热榜一次几分钟，心跳不能被单条任务绑架；
- hot：热榜刷新永远可能卡在网络里，必须独立线程；一轮只刷一个源（照微信 resident.hot_cycle 的轮转），且只在队列空闲时刷。
sqlite 由 LockedConnection 串行化；三条线程都不许绕过它。

**必须补的两条能力（已批准方案里明确包含，之前漏了）**：
1. **链接阅读**：消息文本里出现 http(s) 链接时，用 `web_reader.fetch_public_text(url, cfg['links'])` 读最多 `links.max_urls`（默认 2）个，
   总预算 `links.total_budget_seconds`（默认 12）秒；结果作为 `web_sources` 传给 `model.reply`（StepPlan 已把它标成 untrusted）。
   任何失败/超时/超量 → 退回空列表，**绝不能影响文字回复**；只读公网 http/https，沿用 web_reader 的 DNS 固定与协议限制。
2. **风格自学习**：照微信 `resident.learn_cycle` 的语义接进 QQ 循环——某会话 `memory.note_messages` 累计 ≥ `LEARN_EVERY`(20) 时，
   在**队列空闲**时用 `memory.learning_sample(ck)` + `memory.learn(ck, sample, model)` 学一次；
   消耗一次额度（priority=GROUP_PLAIN）、失败按指数退避（1h→2h→…上限 24h）、成功后 1 小时内不再学；
   学习样本只取对方发言（ChatMemory 已保证），敏感样本剔除也由它保证。
## 10. 独立验证后的裁决（lead，2026-10-18 晚；qq-verifier 报告 verify_qq/REPORT.md）

**§9 补充字段**（qq-core 已实现，示例配置必须跟上）：
```jsonc
  "links": { "enabled": true, "max_urls": 2, "max_bytes": 250000, "max_chars": 9000,
             "timeout": 10, "total_budget_seconds": 12 }
```
- `links.enabled` 默认 **true**（与微信侧一致：用户贴链接就该能读，读不到只记 unreadable）。
- `hot_feed.enabled` 默认 **false**：RSSHub 是第三方慢源，装机即出网不合适；要热榜就显式打开（打开后走独立线程、一轮一源、空闲才刷）。

**裁决（写进契约，避免下次再争）**：
- **D11 / S3**：`at_all`（@全体）与 `[CQ:reply]`（引用回复）都**不算**"被 @"。`at_only` 群里它们只进上下文不接话；要接就显式把该群设为 `selective`/`idle`/`all`。这是刻意的（@全体是发给所有人的通知，回它是噪音）。
- **S1**：`groups[g]` 里 `plain_mode`/`followup_window_s`/`plain_cooldown_s`/`plain_per_hour`/`mention_aliases` 类型写错时，按"该字段缺失"处理，**不影响真 @ 的回复**（@ 路径根本不读这些字段）。§3 开头那句"类型不对 → ignore"只适用于"会话身份/名单"这类决定**能不能接**的字段（chat_type、direct_policy、名单本身）。
- **S2**：`plain_mode` **只在群条目里生效**（顶层写 plain_mode 无效，退回 at_only）；其余四个字段支持"群条目 → 顶层"回退。方向更保守，保留。
- **D7**：端口 0 视为非法（`public_endpoint` 里 `p.port` 为 0 直接拒），不要折成 80。
- **D6**：`public_endpoint` 除了 `is_global` 还要拒 `is_multicast`/`is_reserved`（Python 里 224.0.0.1 的 is_global 是 True，必须显式挡）。
**§10 追加口径（2026-10-18 19:25，回答 qq-verifier 的 OBSERVE）**：
- `mention_aliases` 类型写错（不是 list）时，按**最保守**解释 = **当没有别名**（不退回全局别名、不猜）。
  这是 §10-S1"按字段缺失处理"的一次明确化：缺失/写错都退到"该字段的最保守取值"，而不是"另一个来源的值"。
- `plain_mode` 保持"只在群条目里读"，顶层写好也不生效（更保守）。
