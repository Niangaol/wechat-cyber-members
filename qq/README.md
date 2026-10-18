# QQ 接入（NoneBot2 + NapCat）

年糕 Agent 的 QQ 侧入口。与微信侧（`src/` + 纯 UI 自动化）**完全独立**：QQ 走官方 OneBot v11
协议，不截图、不模拟点击；两边共用同一份模型与搜索凭据，但各自的状态目录 / db / 额度独立。

数据流（一条消息的生命周期）：

    NapCat（QQ 客户端，ws 客户端）
        │  反向 WebSocket：ws://127.0.0.1:18080/onebot/v11/ws（Authorization: Bearer <token>）
        ▼
    nonebot2（本目录 bot.py 启动，FastAPI 驱动，只监听 127.0.0.1）
        │  qq/plugins/qq_chat.py：event.dict() → qq.core.envelope.from_onebot_event() → service.submit()
        │  ↑ 只入队，**不 await 模型**（事件循环必须保持轻）
        ▼
    qq/core/service.py（qq-core 写的同步核心，跑在自己的 owner 线程）
        │  策略判定 → 记时间线 → 下载图片 → 生成回复 → 发送
        ▼
    qq/bot.py 的 NoneBotSender（asyncio.run_coroutine_threadsafe 桥回事件循环）
        ▼
    bot.call_api('send_msg', ...)  →  只回到这条消息自己的会话

## 文件

| 文件 | 作用 |
| --- | --- |
| `qq/bot.py` | 入口：读配置 → `nonebot.init()` → startup 钩子里造 `NoneBotSender` + `QQService` → 加载插件 |
| `qq/plugins/qq_chat.py` | 插件：`on_message` 只做入队；`/qqstatus` 排障（仅 SUPERUSERS） |
| `qq/plugins/__init__.py` | 服务单例 + `event_payload()` / `format_status()`（纯标准库，离线可测） |
| `qq/config/qq.example.json` | 配置示例（schema 见 `qq/core/INTERFACES.md` 第 9 节，冻结版） |
| `qq/requirements.txt` | 依赖，版本钉死 |
| `test_qq_plugin.py` | 本层的离线单测（不装 nonebot、不连网也能跑大部分） |

## 一、安装

需要 Python ≥ 3.10（WSL 是 3.12.3）。Ubuntu 24.04 的系统 python 是 externally-managed，
不要直接 `pip install` 到系统环境（会报 externally-managed-environment），用 venv：

```bash
wsl -d Ubuntu-24.04 -- bash -lc '
  cd /mnt/d/AgentPrograms/wechat-bot
  python3 -m venv ~/.local/share/qq-bot/venv
  ~/.local/share/qq-bot/venv/bin/python -m pip install -U pip
  ~/.local/share/qq-bot/venv/bin/python -m pip install -r qq/requirements.txt
'
```

### 版本依据（2026-10-18）

| 包 | 钉的版本 | 依据 |
| --- | --- | --- |
| nonebot2 | 2.5.0 | PyPI 最新稳定版（2026-04-01 上传）；requires-python `>=3.10,<4.0` |
| nonebot-adapter-onebot | 2.4.6 | PyPI 最新版（2024-10-24 上传）；要求 `nonebot2>=2.2.0,<3.0.0`，与 2.5.0 兼容 |
| pillow | >=10.2 | `qq/core/media.py` 用 PIL 校验图片；系统 python 已有 10.2.0，venv 里要显式装 |

复核命令（想升级时自己再跑一遍，别照抄老文档）：

```bash
curl -s https://pypi.org/pypi/nonebot2/json | python3 -c "import json,sys; print(json.load(sys.stdin)['info']['version'])"
curl -s https://pypi.org/pypi/nonebot-adapter-onebot/json | python3 -c "import json,sys; print(json.load(sys.stdin)['info']['version'])"
```

另外核对了 2.4.6 的源码（sdist）以确保两件事：反向 ws 路由确实是 `/onebot/v11/ws`；
鉴权读的是请求头 `Authorization: Bearer <token>`（配置键 `onebot_access_token`），
所以 `QQ_BOT_ONEBOT_TOKEN` 必须和 NapCat 里填的一模一样。

## 二、配置

```bash
cd /mnt/d/AgentPrograms/wechat-bot
cp qq/config/qq.example.json qq/config/qq.json   # qq.json 不进仓库
```

必须改的只有三处：

1. **token**：`export QQ_BOT_ONEBOT_TOKEN='<随机串>'`（推荐，环境变量优先），或写进
   `qq.json` 的 `onebot.token`。**两者都空时 bot 直接拒绝启动**（fail-closed，绝不开无鉴权监听）。
   这个串要一字不差地填进 NapCat 的反向 ws 配置。
2. **要接的群**：`groups` 初始是 `{}`（谁都不接）。把 `_groups_示例` 里的条目搬进 `groups`，
   键换成真实**群号字符串**（如 `"123456789"`）。两种常用策略：
   - `at_only`（默认，最保守）：只有 @ 它 / 喊名字 / 刚回过话 60 秒内的追问才回，闲聊只当上下文；
   - `idle`：在上面基础上，空闲（队列空 + 冷却过了）时普通闲聊也接一句。
3. **`auto_send`**：首次部署保持 `false`（只记录/入队不发送），联调确认事件与队列正常后再改 `true`。

端口与路径默认 `127.0.0.1:18080` + `/onebot/v11/ws`。临时联调可以用 `QQ_BOT_PORT` /
`QQ_BOT_HOST` 覆盖；配置文件路径可用 `QQ_BOT_CONFIG` 覆盖（默认 `qq/config/qq.json`）。

两个默认值记住就行：`links.enabled=true`（别人贴 http(s) 链接时会读，最多 2 个、总预算 12 秒，
读不到不影响文字回复）；`hot_feed.enabled=false`（RSSHub 是第三方慢源，**要热榜自己开**）。

密钥都不进这两个文件：`model` / `web_search` / `image_generation` 的 `credential_file` 都指向
**微信那份共享凭据** `/home/niangao/.local/state/wechat-bot/credentials.json`（600 权限、只读复用，
不复制、不轮换两次）。生图默认 `enabled=false`。

## 三、NapCat 侧要配的三件事

1. 反向 WebSocket：url = `ws://127.0.0.1:18080/onebot/v11/ws`（与 `onebot.port` + `onebot.path` 对上）；
2. 同一个 access token（NapCat 的"Token"字段 = `QQ_BOT_ONEBOT_TOKEN`）；
3. WebUI 绑 `127.0.0.1`（`0.0.0.0` 等于把管理面板暴露到局域网，不合格）。

## 四、启动与自检

```bash
# 自检：校验配置/token/依赖/路由，不启动服务、不占端口（0=可启动 2=配置不合格 3=依赖缺失）
wsl -d Ubuntu-24.04 -- bash -lc 'cd /mnt/d/AgentPrograms/wechat-bot && QQ_BOT_ONEBOT_TOKEN=xxx ~/.local/share/qq-bot/venv/bin/python -m qq.bot --check'

# 启动（前台；Ctrl-C 退出）
wsl -d Ubuntu-24.04 -- bash -lc 'cd /mnt/d/AgentPrograms/wechat-bot && export QQ_BOT_ONEBOT_TOKEN=xxx && ~/.local/share/qq-bot/venv/bin/python -m qq.bot'

# 常驻/开机自启用 systemd 用户服务：见 qq-deploy 写的 wsl/qq-*.service 与 docs/QQ.md（本文件不重复）
```

启动日志里会明确写出监听地址、state_dir、`auto_send` 状态；`auto_send=false` 时会有一条
警告提醒"只记录不发送"。停止：`Ctrl-C`，或在 state_dir 里放一个 `STOP` 文件（worker 会停手不发送）。

## 五、离线测试

```bash
wsl -d Ubuntu-24.04 -- bash -lc 'cd /mnt/d/AgentPrograms/wechat-bot && python3 -m unittest test_qq_plugin -v'
```

测试不装 nonebot 也能跑（用到 nonebot 的用例会自动 skip）；不连网、不连真实 QQ/微信、
不碰生产库：用的是假 bot + 假事件循环 + 临时目录。

## 六、`/qqstatus`

私聊或群里发 `/qqstatus`，回一条状态（状态/心跳/队列深度/绑定账号/连接/最近事件/最近发送成功/
最近错误/本小时已发/STOP）。**只有 SUPERUSERS 能查**，默认（没配）谁都查不到：

```bash
export SUPERUSERS=你的QQ号      # 多个用逗号分隔；NoneBot 读这个环境变量
```

## 七、排障速查

| 现象 | 原因 / 处理 |
| --- | --- |
| 启动就退出，日志说没有可用 access token | 环境变量与 `onebot.token` 都空。设 `QQ_BOT_ONEBOT_TOKEN` |
| NapCat 连上马上被断，日志 403 Missing/Invalid Authorization Header | 两端 token 不一致（注意适配器只看 Bearer 头） |
| NapCat 报 404 / 连不上 | `onebot.path` 不是适配器写死的三个路由之一，或端口没对上 |
| 收到消息但一直没回复 | `auto_send=false`（总闸关着）；或该群没登记进 `groups`；或额度/频率闸拦下了（看状态与日志） |
| `/qqstatus` 没反应 | 没配 `SUPERUSERS`（默认拒绝），或当前 QQ 号不在里面 |
| 图片发不出去 | 图片超过 `MAX_IMAGE_BYTES`(10MB) 或 `send_image` 报 unknown —— unknown 表示"可能已发出"，**不会重发** |
| 想确认没连真 QQ 也不会误发 | 把 `auto_send` 保持 `false`，或在 `state_dir` 放 `STOP` 文件 |
