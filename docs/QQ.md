# QQ 接入部署手册（NapCat + NoneBot2）

> **这一页是什么**：把 QQ 接进本仓库的完整部署/运维手册——装什么、改什么、怎么验、怎么退。
> 微信链路（`wechat-stack` / `wechat-bot` / `wechat-soak`）**一行都不动**，QQ 是完全独立的第二套链路。
>
> **现在的状态**：代码与脚本已就位；**10-18 20:32 已实机连通**（NapCat 作为 Bot 3805074324 连上 NoneBot，`journalctl --user -u qq-bot` 有 `connection open` 实证），当时 `auto_send=false` 只记录不发送，20:33 按计划停止。`qq-bot.service` / `qq-napcat.service` 已安装但默认 disabled。**放量前按下面第 10 节的闸门一步步放，别跳步。**

---

## 0. 先读这一段：风险与边界

| 项 | 说明 |
|---|---|
| **非官方接入** | NapCat 是社区第三方项目（基于 QQ NT 客户端的 OneBot 11 适配器），**不是腾讯官方接口**。使用它可能违反腾讯的用户协议，存在**账号风控、限制登录、封号**的现实风险。 |
| **用哪个号** | 只用**你自己的小号/测试号**，别拿主号试。第一次联调前先确认这个号封了也不心疼。 |
| **频率** | 新号 + 高频自动回复是最容易被盯上的组合。闸门设计成"先 STOP、再私聊、最后群 @"，就是为此。 |
| **数据** | QQ 号、token、密钥**不进仓库**；`~/.config/qq-bot/qq.env`（600）与 `qq.json`（600）都在本机。日志里也不打印 token 明文（验收脚本只输出长度与 sha256 前 8 位）。 |
| **与微信的隔离** | QQ 服务是独立的 systemd 用户单元，`PartOf`/`BindsTo`/`Requires` 都**不指向**微信服务；QQ 的验收/体检脚本不读也不写 `~/.local/state/wechat-bot/`。停 QQ 不会影响微信。 |

---

## 1. 架构

```
Windows 宿主（你看到的这台机器）
 │
 │  wsl.exe -d Ubuntu-24.04 -- bash -lc '...'      ← 命令都从这里进
 ▼
WSL2 Ubuntu-24.04（systemd 用户服务；用户 niangao）
 │
 ├─ 【微信链路，已有，本手册不碰】
 │    wechat-stack.service → Xvfb :99 + 微信客户端 + x11vnc :5900 + noVNC :6080
 │    wechat-bot.service   → src/resident.py（截图 + OCR + 键鼠）
 │
 └─ 【QQ 链路，本手册新增】
      NapCat（QQ NT 客户端 + OneBot 适配器）
        · 位置：~/Napcat/opt/QQ（rootless 安装，本机现状）
        · 跑法：xvfb-run -a ~/Napcat/opt/QQ/qq --no-sandbox（一次性虚拟屏，不用 :99）
        · WebUI：http://127.0.0.1:6099/webui/（只绑回环）
        · 角色：**WebSocket 客户端（反向 WS）**——它主动连 NoneBot
              │  ws://127.0.0.1:18080/onebot/v11/ws   + token
              ▼
      qq-bot.service  ←  ~/.local/share/qq-bot/venv/bin/python -m qq.bot
        · NoneBot2 + nonebot-adapter-onebot：**监听 127.0.0.1:18080**（反向 WS 服务端）
        · qq/plugins/qq_chat.py 只做一件事：事件 → from_onebot_event() → service.submit()（永不 await 模型）
        · 发送：bot.call_api('send_msg', ...) 由 NoneBotSender 回到同一个会话
              │
              ▼
      qq/core（平台无关的同步实现，复用 src/ 的共享模块）
        · envelope 解析 → policy 判定 → Quota 分级队列 → memory 记忆
        · 要写内容才调模型（StepPlan + model.reply），生图/搜索各有限额
        · 状态全在 ~/.local/state/qq-bot/（db / media / STOP / status.json，700）
              │
              ▼
      大模型（与微信共用同一套凭据文件，额度池各自独立）
```

**端口分配（本机实测：5900/6080 已被微信占用）**

| 端口 | 绑定 | 谁在用 | 备注 |
|---|---|---|---|
| 18080 | 127.0.0.1 | `qq-bot.service`（NoneBot） | NapCat 作为客户端连过来 |
| 6099 | 127.0.0.1 | NapCat WebUI | **必须**回环；被占用会自动 +1，端口看启动日志 |
| 6080 / 5900 | 127.0.0.1 | 微信链路（noVNC / VNC） | **别动**，也别拿来给 QQ 用 |

**为什么 QQ 不需要虚拟屏、微信需要**：微信走的是纯 UI 自动化（截图 + 键鼠），必须有显示；
QQ 走的是 OneBot 网络协议，`qq-bot.service` 里显式 `UnsetEnvironment=DISPLAY`，从设计上就碰不到 `:99`。
NapCat 自己是 QQ 客户端，确实需要 X，但用 `xvfb-run` 开**自己的**一次性屏，与微信互不干扰。

---

## 2. 前置条件

| 项 | 要求 | 怎么查 |
|---|---|---|
| WSL2 + systemd | 已开启（本机已有） | `systemctl --user is-system-running` |
| 发行版/用户 | Ubuntu-24.04 / niangao | `wsl.exe -d Ubuntu-24.04 -- id -un` |
| Python | 3.10+（本机 3.12.3） | `python3 -V` |
| pypi 可达 | 装依赖用（只装一次） | `python3 -m pip download --no-deps -d /tmp/t nonebot2` |
| xvfb | NapCat（QQ 客户端）需要 X | `command -v xvfb-run` |
| 端口 | 18080、6099 空闲 | `ss -ltnH 'sport = :18080'` |
| 磁盘 | 约 1GB（QQ + NapCat） | `df -h ~` |
| 手机 | 装有 QQ，能扫码 | — |

---

## 3. 装 QQ 侧运行环境（本仓库负责的部分）

```bash
# 在 Windows 上直接执行（会进 WSL）
wsl.exe -d Ubuntu-24.04 -- bash /mnt/d/AgentPrograms/wechat-bot/wsl/install-qq.sh --dry-run   # 先看它要干什么
wsl.exe -d Ubuntu-24.04 -- bash /mnt/d/AgentPrograms/wechat-bot/wsl/install-qq.sh             # 真装
```

脚本**会做**（幂等，可重复跑）：

1. 建 QQ 专用 venv：`~/.local/share/qq-bot/venv`，并 `pip install -r qq/requirements.txt`
2. 建目录：状态 `~/.local/state/qq-bot`（700）、配置 `~/.config/qq-bot`（700）
3. 生成 `~/.config/qq-bot/qq.env`（600，含随机 token）、`napcat.env`（600，模板）、
   `qq.json`（600，从 `qq/config/qq.example.json` 复制）
4. 把 `wsl/qq-bot.service`、`wsl/qq-napcat.service` 拷到 `~/.config/systemd/user/` 并 `daemon-reload`

脚本**不做**（刻意留给人和授权）：不 sudo、不装系统包、不装 NapCat、不改 NapCat 配置、
**不 enable、不 start 任何服务**、不碰微信的任何文件与服务。
（`daemon-reload` 只是让 systemd 重读单元文件，不会重启/停止正在跑的微信服务。）

装完的样子：

```bash
stat -c '%a %n' ~/.config/qq-bot ~/.config/qq-bot/qq.env ~/.local/state/qq-bot
# 700 /home/niangao/.config/qq-bot
# 600 /home/niangao/.config/qq-bot/qq.env
# 700 /home/niangao/.local/state/qq-bot
```

---

## 4. 装 NapCat（第三方组件；官方来源）

> **这一步会装系统包/写系统目录，必须由人执行并知晓**。官方文档：<https://napneko.github.io/guide/boot/Shell>
> 本机**已经装好**（rootless 方式，路径 `~/Napcat`），所以这一节主要是"换机器时怎么装"和"它到底改了什么"。

### 4.1 官方一键脚本（默认会用到 sudo）

```bash
# 官方写法：依次尝试加速源，最后回落直连（来源：napneko.github.io/guide/boot/Shell）
curl -fsSL -o napcat.sh https://ghfast.top/https://raw.githubusercontent.com/NapNeko/NapCat-Installer/main/script/install.sh \
  || curl -fsSL -o napcat.sh https://ghproxy.net/https://raw.githubusercontent.com/NapNeko/NapCat-Installer/main/script/install.sh \
  || curl -fsSL -o napcat.sh https://raw.githubusercontent.com/NapNeko/NapCat-Installer/main/script/install.sh
sudo bash napcat.sh          # 交互式；也可加 --docker n --cli n --proxy 0 --force 等参数
```

**它会改什么（先看清楚再按回车）**：

- 安装 QQ NT Linux 客户端（约几百 MB）到 `/opt/QQ`（或你指定的目录，rootless 模式装到 `~/Napcat/opt/QQ`）
- 把 NapCat Shell 解压到 `<QQ目录>/resources/app/app_launcher/napcat`，并改 QQ 的 `package.json` 入口以加载 NapCat
- 生成 `<上述目录>/config/webui.json`（WebUI 的 host/port/token）
- 可能注册开机自启（systemd 服务或类似机制）——**本机为了跟微信隔离，没有用它自带的托管方式**

### 4.2 无桌面环境依赖（QQ NT 需要 X）

```bash
sudo apt install -y xvfb xauth jq
```

### 4.3 手动安装（不想用一键脚本时，官方 semi-auto 路线）

来源：<https://napneko.github.io/guide/boot/Shell-Linux-SemiAuto>。
把 `NapCat.Shell.zip` 解压到 `/opt/QQ/resources/app/napcat`，写 `loadNapCat.cjs` 加载器，
再用 `jq` 把 `/opt/QQ/resources/app/package.json` 的 `main` 指向它（改前先备份原文件）。细节以上面官方页面为准。

### 4.4 启动（前台先跑通，再考虑常驻）

```bash
# 前台（第一次一定这样跑，能直接看到日志与 WebUI 地址）
xvfb-run -a ~/Napcat/opt/QQ/qq --no-sandbox
# 想免扫码快速登录（QQ 号别写进仓库）：
xvfb-run -a ~/Napcat/opt/QQ/qq --no-sandbox -q <你的QQ号>
```

三种常驻方式，**三选一，别同时开**（两个 QQ NT 进程抢同一份配置目录会互相踢下线）：

| 方式 | 命令 | 说明 |
|---|---|---|
| screen（最省事） | `screen -dmS napcat xvfb-run -a ~/Napcat/opt/QQ/qq --no-sandbox`<br>`screen -r napcat` 看日志，`screen -S napcat -X quit` 停 | 简单，但 WSL 重启后不会自动回来 |
| 本仓库的**用户级**单元 | `systemctl --user enable --now qq-napcat` | 文件 `wsl/qq-napcat.service`；`ConditionPathExists=%h/Napcat/opt/QQ/qq` 保证没装时不刷报错；快速登录参数写在 `~/.config/qq-bot/napcat.env` 的 `QQ_BOT_QQ_ARGS` |
| 官方**系统级**模板 | 见 <https://napneko.github.io/guide/boot/Linux_startup>，单元放 `/etc/systemd/system/napcat.service`，`ExecStart=/usr/bin/xvfb-run -a /opt/QQ/qq --no-sandbox` | 仅当你用 sudo 装到 `/opt/QQ` 时用；系统级服务操作要 sudo |

---

## 5. WebUI 首次登录与改密

1. 启动 NapCat 后，日志里会出现形如
   `[info] [NapCat] [WebUi] WebUi User Panel Url: http://127.0.0.1:6099/webui?token=xxxxx`
   没记下来的话，token 就在配置文件里：
   ```bash
   cat ~/Napcat/opt/QQ/resources/app/app_launcher/napcat/config/webui.json
   # {"host":"0.0.0.0","port":6099,"token":"xxxx","loginRate":3}
   ```
   （sudo 装到 `/opt/QQ` 的话，路径是 `/opt/QQ/resources/app/app_launcher/napcat/config/webui.json`。）
2. 浏览器打开 `http://127.0.0.1:6099/webui/`（**用 127.0.0.1，不要用 WSL 的 IP**）。
3. 左侧「QQ 登录」→ 点 **QRCode** → 手机 QQ 扫码 → 手机端确认。
   ⚠️ 扫码这一步会刷新 WebUI token：新 token 在**手机端自己的消息**里，或 NapCat 控制台里。
4. 重新进入 WebUI 后**会强制要求改密码**，不改就没法用大部分功能——改掉，记到密码管理器里。
5. **把 WebUI 的 host 改成 `127.0.0.1`**。官方默认 `0.0.0.0`（监听所有地址），在 WSL 里等于暴露给整个局域网/宿主机，
   面板被扫到就等于把 QQ 号交出去了。改完重启 NapCat。验收脚本会对这一条直接报 FAIL。
6. 端口被占用时 NapCat 会自动 `+1` 直到找到空闲端口（最多 100 次），实际端口看启动日志——**不要**假设一定是 6099。

---

## 6. NapCat 的网络配置：建一个"WebSocket 客户端（反向 WS）"

概念（官方《WebUI 配置指南》）：**反向 WS** 指 NapCat 作为**客户端**主动连到框架（NoneBot）；框架只负责监听。
QQ 侧架构就是这么定的：NoneBot 监听 18080，NapCat 连过来。

WebUI → 网络配置 → **新建 → WebSocket 客户端**，按下表填（**保存时启用**要勾上）：

| 字段 | 值 | 为什么 |
|---|---|---|
| 名称 | `nonebot`（随意，唯一即可） | — |
| URL | `ws://127.0.0.1:18080/onebot/v11/ws` | 端口与路径必须与 `qq.json` 的 `onebot.port`/`onebot.path` **完全一致** |
| Token | 与 `~/.config/qq-bot/qq.env` 里的 `QQ_BOT_ONEBOT_TOKEN` **完全一致** | 不一致 → 连接被 403 拒掉（见第 12 节） |
| messagePostFormat | `array` | 消息段用结构化数组；`string` 会退化成 CQ 码字符串，走最小解析，不如 array 可靠 |
| reportSelfMessage | `false` | 自己的消息不上报；true 会把自己的回复也当成入站事件 |
| 重连间隔 / 心跳 | 默认（5000 / 30000）即可 | — |
| 启用 | 勾上 | 没启用等于没配 |

改完可以在 WebUI 里"保存"，也可以直接编辑配置文件（**官方明确不推荐手改**，除非你很清楚）：

```bash
# 登录后会生成 onebot11_<QQ号>.json（也可能叫 onebot11.json）
python3 -m json.tool ~/Napcat/opt/QQ/resources/app/app_launcher/napcat/config/onebot11.json | head -40
```

结构（官方字段名）：

```jsonc
{
  "network": {
    "websocketClients": [
      {
        "name": "nonebot",
        "enable": true,
        "url": "ws://127.0.0.1:18080/onebot/v11/ws",
        "messagePostFormat": "array",
        "reportSelfMessage": false,
        "reconnectInterval": 5000,
        "token": "<与 QQ_BOT_ONEBOT_TOKEN 一致>",
        "debug": false,
        "heartInterval": 30000
      }
    ]
  }
}
```

**谁先启动无所谓**：NapCat 是客户端，连不上会按 `reconnectInterval` 一直重试；推荐先起 NoneBot 再起 NapCat，日志更干净。

---

## 7. NoneBot 侧起停（`qq-bot.service`）

```bash
# 起之前先做一次启动自检（qq.bot --check：0=可启动 / 2=token 或端口 / 3=依赖或核心模块）
cd /mnt/d/AgentPrograms/wechat-bot
QQ_BOT_CONFIG=$HOME/.config/qq-bot/qq.json \
QQ_BOT_ONEBOT_TOKEN=$(grep ^QQ_BOT_ONEBOT_TOKEN= $HOME/.config/qq-bot/qq.env | cut -d= -f2-) \
$HOME/.local/share/qq-bot/venv/bin/python -m qq.bot --check
# 期望输出：自检结论：可以启动。

# 起（enable 一次即可，之后 WSL 启动会自动拉起；需要 loginctl enable-linger，install 脚本已尽量开启）
systemctl --user enable --now qq-bot

# 看状态与日志
systemctl --user status qq-bot --no-pager
journalctl --user -u qq-bot -n 50 --no-pager

# 停 / 重启（只动 QQ）
systemctl --user stop qq-bot
systemctl --user restart qq-bot

# 急停（不发送，但进程还在，方便排查）
touch ~/.local/state/qq-bot/STOP
rm -f ~/.local/state/qq-bot/STOP
```

服务定义（`wsl/qq-bot.service`，要点）：

- `ExecStart=%h/.local/share/qq-bot/venv/bin/python -m qq.bot`，`WorkingDirectory=/mnt/d/AgentPrograms/wechat-bot`
- `EnvironmentFile=%h/.config/qq-bot/qq.env`（缺文件会直接启动失败，这是 fail-closed：没配置就别裸奔）
- `Restart=always` + `RestartSec=10`；`UnsetEnvironment=DISPLAY WAYLAND_DISPLAY XAUTHORITY`（碰不到微信的屏）
- 没有 `PartOf`/`BindsTo` 指向微信服务 → 停/起 QQ 不会连带微信

---

## 8. 扫码登录（必须人工一次）

1. 先起 NapCat，再起 `qq-bot`（顺序无所谓，只是日志好读）。
2. 浏览器 → `http://127.0.0.1:6099/webui/` → QQ 登录 → QRCode → 手机 QQ 扫。
3. 登录成功后，NapCat 侧会生成 `onebot11_<QQ号>.json` 并开始按配置连 18080。
4. 回到 WSL 验证连接：

```bash
python3 /mnt/d/AgentPrograms/wechat-bot/wsl/qq-health.py --pretty
# 期望： "ws_connected": true, "online": true, "ok": true, "reasons": []
```

5. **掉登录**：`online` 变 false、`reasons` 里出现 "QQ 未在线" → 回 WebUI 重新扫码（第 12 节）。

---

## 9. 能力与配置语义（links 链接阅读 / hot_feed 热榜 / 群判定裁决）

> 口径以契约 `qq/core/INTERFACES.md` §9（配置 schema）与 §10（裁决）为准。这一节讲"默认值是什么、开了会发生什么"。

### 9.1 三个"外部信息源"，别混

| 能力 | 配置段 | 默认 | 谁触发 | 走哪儿 |
|---|---|---|---|---|
| 联网搜索 | `web_search` | 开（需要有凭据文件） | **模型自己**判断要不要查（function calling） | Tavily（第三方 API） |
| 链接阅读 | `links` | **开** | 消息文本里**出现 http(s) 链接**就自动读 | 直接抓那个网页（受限，见 9.2） |
| 热榜 | `hot_feed` | **关** | 定时刷新，闲时当"热点背景"喂给模型 | RSSHub（第三方慢源） |

**`hot_feed` 默认 `false` 是刻意的**：RSSHub 是第三方慢源，装机即出网不合适。要热榜就显式打开（`hot_feed.enabled=true` + `refresh_seconds`）：

```jsonc
"hot_feed": { "enabled": true, "refresh_seconds": 300 }
```

打开后热榜刷新走**独立线程、一轮只刷一个源、且只在队列空闲时刷**（契约 §7.1）——
它不会再拖住回复，也不会绑架 `status.json` 心跳（这条是真踩过坑的，见常见故障对照表）。

### 9.2 链接阅读（`links`，默认开）

```jsonc
"links": { "enabled": true, "max_urls": 2, "max_bytes": 250000, "max_chars": 9000,
           "timeout": 10, "total_budget_seconds": 12 }
```

| 字段 | 默认 | 含义 |
|---|---|---|
| `enabled` | **true** | 与微信侧一致：用户贴链接就该能读；不想读就显式 `false` |
| `max_urls` | 2 | 一条消息里最多读几个链接（多出来的不读，也不影响别的） |
| `max_bytes` | 250000 | 单个页面最多取多少字节 |
| `max_chars` | 9000 | 送进模型的正文字符上限（超出截断） |
| `timeout` | 10 | 单个请求超时（秒） |
| `total_budget_seconds` | 12 | **整体预算**：一次回复里所有链接加起来最多花这么久 |

运维要知道的三条语义：

1. **只读公网 http/https**：沿用 `web_reader` 的 DNS 固定（防重绑定）与端口白名单；
   私网/本机/组播等地址一律拒（契约 §10 D6；端口 0 视为非法，不折成 80）。
2. **读不到不影响回话**：超时、超量、不是 HTML、被拒 → 只记一条 `unreadable`，正文退回空列表，
   **照常回文字**。"链接没读到"永远不会变成"这条消息没回"。
3. **只读消息里出现的链接**，不会顺着网页里的外链爬（那是 `web_search` 的活）。

排查与调参：
```bash
journalctl --user -u qq-bot | grep -i unreadable     # 哪些链接没读到
# 嫌慢：调小 timeout / total_budget_seconds；嫌吵：links.enabled=false 后 systemctl --user restart qq-bot
```

### 9.3 群判定裁决（契约 §10，避免误配）

- **@全体（at_all）与引用回复（`[CQ:reply]`）都不算"被 @"**：`at_only` 的群里它们**只进上下文、不接话**；
  想让它们接话，就把该群显式设成 `selective`/`idle`/`all`。这是刻意的——@全体是发给所有人的通知，回它是噪音。
- **`plain_mode` 只在群条目里生效**：写到顶层无效（退回 `at_only`）；
  `plain_cooldown_s` / `plain_per_hour` / `followup_window_s` / `mention_aliases` 支持"群条目 → 顶层"回退。
- **群条目里某个字段类型写错**（例如 `plain_cooldown_s: "120"`）按"该字段缺失"处理，**不影响真 @ 的回复**
  （@ 路径根本不读这些字段）；但决定"能不能接"的字段（`chat_type`、`direct_policy`、名单本身）仍然 fail-closed。

---

## 10. 分阶段上线闸门（**别跳步**）

`qq.json` 里 `auto_send` 是总闸，默认 `false`；`groups` 默认空（谁都不接）。
上线顺序就是"一次只放开一点，每步都能退回来"：

> 闸门只管"发不发消息"。另两个能力段的默认值见第 9 节：`links`（链接阅读）**默认开**、
> `hot_feed`（RSSHub 热榜）**默认关**；它们都不会绕过 `auto_send` 直接发东西，但热榜开着会多一份出网流量。

| 阶段 | 目标 | 怎么做 | 通过标准 | 出问题怎么退 |
|---|---|---|---|---|
| **G0 只连接** | 确认 NapCat ⇄ NoneBot 通了，一条都不发 | `auto_send=false`、`groups={}`、STOP 在位 | `qq-health.py` 的 `ws_connected=true`、`online=true` | 直接停服务，什么事都没有 |
| **G1 私聊·只记录** | 确认事件能进队列、记忆在写 | 摘掉 STOP（或留着 STOP 只看日志）、用一个测试小号给自己发消息 | `journalctl -u qq-bot` 里有入站事件；`status.json` 的 `last_event_at` 在更新 | `touch STOP` |
| **G1.5 假 NapCat·验通链路** | **不用真实 QQ** 先把"事件→策略→队列→模型→安全闸→send_msg→台账"整条链验通（详见 10.1 节） | `auto_send=true`、`direct_whitelist` 只放测试号、`groups` 只登记测试群（`at_only`）→ 跑 `wsl/qq-e2e-live-check.sh` → 验完把 `auto_send` 改回 `false` | 4 条场景全对：私聊**收到** send_msg、群里不 @ **不发送**、群里真 @ **发给 group_id**、同 message_id 重投**不回复** | `auto_send=false` + `touch STOP` 后 `systemctl --user restart qq-bot` |
| **G2 私聊·真回复** | 打通"生成 → 发送" | `auto_send=true`，`direct_policy` 用 `whitelist` 且 `direct_whitelist` 只放你的测试号 | 测试号收到回复；`status.json` 的 `last_send_ok_at` 更新 | `touch STOP` 或把 `auto_send` 改回 false 后 `systemctl --user restart qq-bot` |
| **G3 群·只接 @** | 群里只回被 @ 的 | `groups` 里**只加测试群**，`plain_mode=at_only` | 在群里 @ 机器人 → 有回复；不 @ 时**不回复**（进程仍在记录） | 把该群从 `groups` 删掉并重启服务 |
| **G4 群·闲时接话** | 慢慢放开普通消息 | 视情况把 `plain_mode` 改成 `idle`（配合 `plain_cooldown_s`/`plain_per_hour`） | 观察一天：无刷屏、无重复回复、额度没被打穿 | 改回 `at_only` |

**G0/G1 阶段的额外保险**：`~/.local/state/qq-bot/STOP` 存在时 worker 停手不发送，队列照收——排查时非常好用。

### 10.1 G1.5：不用真实 QQ 就能验通链路（假 NapCat）

两个工具（都在 `wsl/` 下）：

| 文件 | 作用 |
|---|---|
| `wsl/qq-e2e-fake-napcat.py` | **假 NapCat 客户端**：带 `Authorization: Bearer <token>` 连上反向 WS（默认 `ws://127.0.0.1:18080/onebot/v11/ws`），投一条 OneBot 事件，然后等机器人主动调 `send_msg` 并回成功应答，把模型真正生成的那句话打印出来 |
| `wsl/qq-e2e-live-check.sh` | 一键跑下面 4 个场景 + 打印最近日志与台账 |

单跑一条：

```bash
VENV=~/.local/share/qq-bot/venv/bin/python
$VENV wsl/qq-e2e-fake-napcat.py --help
# 常用参数：--chat-type private|group · --user 20002 · --group 888777 · --at · --message-id 930001 · --timeout 100
#           --text "自定义一句" · --url ws://127.0.0.1:18080/onebot/v11/ws · --self-id 10001
#           --image-url <公网URL>（消息里带一张图）· --expect N（等第 N 条 send_msg 才收工）
```

退出码：**0** = 收到并应答了 `send_msg`；**2** = 超时（**这正是"应该不发送"场景的期望结果**）；**3** = 配置/依赖问题（比如读不到 token）。

**收图 / 生图场景**（两个参数，2026-10-18 新增）：

| 参数 | 默认 | 用途 |
|---|---|---|
| `--image-url <公网URL>` | 空 | 消息里带一张图（image 段），用来验证"收图理解"；**取不到图时正确行为是回"这张图没取到，我看不到哦"，而不是猜内容**（见第 12 节） |
| `--expect N` | 1 | 等到**第 N 条** `send_msg` 才收工。**生图场景必须写 `--expect 2`**：机器人先发文字、再发生图，两条都得应答到 |

```bash
# 收图理解（图片走公网 URL，机器人自己去抓；取不到就该说"没取到"）
$VENV wsl/qq-e2e-fake-napcat.py --user 20002 --message-id 930010 --image-url https://example.com/a.png --timeout 120
# 让它生图：先文字后图片 → 等两条 send_msg
$VENV wsl/qq-e2e-fake-napcat.py --user 20002 --message-id 930011 --text "给我画一张年糕的照片" --expect 2 --timeout 180
```

**自己写客户端时必须知道的两件事**（这个工具已经替你踩过）：

1. **`max_size` 要放大**：图片是以 base64 塞在 `send_msg` 里发过来的（实测一张 ~4.4MB），
   websockets 客户端**默认只收 1MiB**，会把帧判成 `1009 message too big` 直接断开连接——本工具设的是 **32MiB**。
2. **每个 `echo` 只能应答一次**：同一个 `echo` 回两次，会让适配器的 ResultStore 对已完成的 future 再 `set_result`
   （`InvalidStateError`），表现为服务端直接断开这条 WS。

一键回归（前置：`auto_send=true`、测试号在 `direct_whitelist` 里、测试群已登记且 `plain_mode=at_only`）：

```bash
wsl -d Ubuntu-24.04 -- bash /mnt/d/AgentPrograms/wechat-bot/wsl/qq-e2e-live-check.sh
# 在 Windows 侧 Git Bash 里直接跑时加 MSYS_NO_PATHCONV=1，否则 /mnt/d/... 会被 MSYS 转成
# C:/Program Files/Git/mnt/d/...（实测踩过这个坑）
```

| 场景 | 期望 |
|---|---|
| 1) 私聊（白名单内） | 收到 `send_msg` → `ANSWERED_SEND_MSG_OK` |
| 2) 群里不 @ | **不发送**（超时退出码 2；日志里 `action=context_only`） |
| 3) 群里真 @（at 段） | 收到 `send_msg`，且目标是那个 `group_id` |
| 4) 同 `message_id` 重投 | **不重复回复**（持久去重命中） |

**假 NapCat 证明什么、不证明什么**（别把它当免检章）：

- ✅ **证明**：事件解析 → 策略判定 → 队列 → 模型生成 → 安全闸 → `send_msg` 组装 → 台账落盘，
  这条**我们自己的**链路是通的；4 个场景把"该发的发、不该发的不发、重投不回"都钉住了。
- ❌ **不证明**：QQ 真的把消息投递到对方手机（那必须真实登录 + 真实账号），也不证明 NapCat 的协议实现细节、
  登录保活与账号风控表现。
- 所以 **G2/G3 仍然要扫码后真机做一遍**；G1.5 的价值是把"本来就能自检的部分"提前钉死，
  免得真机联调时把时间浪费在我们自己的 bug 上。

⚠️ 成本与副作用：场景 1 和 3 会**真的各调一次模型**（1 单位额度），且 `auto_send=true` 期间机器人会真的往那个号/群发消息——
**只能用测试号/测试群**；跑完立刻把 `auto_send` 改回 `false` 并 `systemctl --user restart qq-bot`，顺手看一眼 `status.json` 的 `sent_1h`。

---

## 11. 体检与验收（两个脚本）

```bash
# 体检：一行 JSON；ok:true 才算健康，exit 0
python3 /mnt/d/AgentPrograms/wechat-bot/wsl/qq-health.py
python3 /mnt/d/AgentPrograms/wechat-bot/wsl/qq-health.py --pretty    # 人看的缩进版

# 离线验收：跑 test_qq_* 单测 + 配置 schema + STOP 语义 + 权限 + NapCat/NoneBot 一致性，出一张表
python3 /mnt/d/AgentPrograms/wechat-bot/wsl/qq-acceptance.py
python3 /mnt/d/AgentPrograms/wechat-bot/wsl/qq-acceptance.py --no-tests            # 跳过单测（快）
python3 /mnt/d/AgentPrograms/wechat-bot/wsl/qq-acceptance.py --allow-uninstalled   # 还没装时：相关项记 SKIP
python3 /mnt/d/AgentPrograms/wechat-bot/wsl/qq-acceptance.py --json                # 机器可读
```

`qq-health.py` 的字段都**分开报告**，方便一眼分辨"没起来 / 起来了没登录 / 登录了没连上"：

| 字段 | 含义 | 判不健康的原因示例 |
|---|---|---|
| `unit` / `unit_active` | `qq-bot.service` 是否 active | "qq-bot.service 不是 active（当前 inactive）" |
| `process_running` / `pids` | 有没有真的 `qq.bot` 进程（能识别手工前台跑的） | "找不到 qq.bot 进程" |
| `heartbeat_age_s` / `heartbeat_ok` | `status.json` 心跳是否新鲜（<90s） | "没有 status.json" / "心跳不新鲜（N 秒未更新）" |
| `stop` / `stop_file` | 急停在不在位 | "急停生效（…/STOP 存在）" |
| `online` / `self_id` | QQ 是否在线、绑定的号 | "QQ 未在线（status.online=False）：多半是掉登录" |
| `ws_listen` / `ws_estab` / `ws_connected` / `ws_peers` | 18080 有没有监听、有几个 ESTAB 连接 | "端口 18080 没有监听：NoneBot 侧没起来" / "有监听但没有 ESTAB 连接：NapCat 没连上来" |
| `napcat_running` / `napcat_cmd` | NapCat 进程在不在（信息项） | — |
| `queue_depth` / `sent_1h` / `last_event_at` / `last_send_ok_at` / `last_error` | 队列深度、一小时发送数、最后事件/最后成功发送时间、最后的错误 | — |

**关键语义**：只要"活着但没连上/没登录"（`online=false` 或 `ws_connected=false`），就 `ok:false` 并写明原因，**不会**出现"服务 active 就算健康"的假绿灯。

**端到端（不用真实 QQ）**：上面这一节证明的是"配置与代码没问题"；要证明"事件真的能走到 send_msg"，跑第 10.1 节的假 NapCat 回归。

---

## 12. 常见故障对照表

| 现象 | 多半原因 | 怎么确认 | 怎么修 |
|---|---|---|---|
| NapCat 日志连接被拒 / 403 | 两边 token 不一致（最常见） | `python3 wsl/qq-acceptance.py --no-tests` → 看 "NapCat⇄NoneBot 一致性" 那一行 | 把 NapCat 的 WS 客户端 token 改成 `qq.env` 里的 `QQ_BOT_ONEBOT_TOKEN`（或反过来），保存后重连 |
| `qq-health` 报 "18080 没有监听" | `qq-bot` 没起来 / 起崩了 | `systemctl --user status qq-bot`；`journalctl --user -u qq-bot -n 50` | 看日志：缺 `qq.env`（先跑 `install-qq.sh`）、token 为空（会拒绝启动）、依赖没装（重跑 install） |
| 体检报 "有监听但没有 ESTAB" | **NapCat 还没连上来**（没登录 / 没配反向 WS / 客户端没启用）——**这是 NapCat 侧的事，不是 NoneBot 的锅** | `qq-health.py` 里 `ws_listen=true` 但 `ws_estab=0`；`pgrep -af 'NapCat\|opt/QQ'` 看进程在不在；WebUI 看客户端是否"已启用" | 先在 WebUI 扫码登录，再建/启用 WebSocket 客户端（URL 与 token 见第 6 节）；连上后 `ws_estab` 会 ≥1 |
| 热榜开着时服务卡死 / `status.json` 不更新 | **旧版本**把热榜刷新放在了 owner 线程里（一次刷新把整个处理循环堵住），网络一慢就假死 | `journalctl --user -u qq-bot` 长时间**没有新日志**；`qq-health.py` 的 `heartbeat_age_s` 一直涨（心跳停住） | **升级到当前版本**：热榜已是独立线程 + 一轮一源 + 空闲才刷（契约 §7.1），不再绑架心跳；不需要热榜就 `hot_feed.enabled=false` 后重启 |
| `online=false`（掉登录） | QQ 侧被踢下线 / 长时间未活动 | `qq-health.py --pretty` 的 `reasons` | WebUI → QQ 登录 → QRCode 重新扫码（第 8 节） |
| 登录时被要求验证、频繁掉线、发不出消息 | **账号风控**（新号 + 高频自动回复最危险） | 手机 QQ 有安全提示；日志里登录反复失败 | 立刻 `touch STOP` + 停服务；换更"老"的小号；降低频率（`max_replies_per_hour`、`plain_per_hour`）；隔几天再试 |
| WebUI 打不开 | 端口不是 6099（被占用自动 +1）；NapCat 没起 | 启动日志里的 WebUi Url 行；`ss -ltnH 'sport = :6099'` | 按日志里的真实端口访问；先起 NapCat |
| WebUI 能从别的机器访问 | `webui.json` 的 host 是 `0.0.0.0` | `cat .../config/webui.json` | 改成 `127.0.0.1` 后重启 NapCat（验收脚本对这条直接 FAIL） |
| 机器人自己回自己 / 重复回复 | `reportSelfMessage=true`；或 token/端口配错导致消息回环 | 验收脚本的一致性检查 | 改回 `false`；重连 |
| 机器人**描述了图片内容**，但那张图其实取不到 | 不该发生——正常行为是回"这张图没取到，我看不到哦" | 投一条带取不到图片 URL 的消息（实测 `upload.wikimedia.org` 从本机 TLS 握手超时），看它怎么回 | 说明 worker 的 `[图片未取到，无法查看]` 标记、或 system prompt 里"看不清就不猜"的规则被改掉了 → 改回来；**绝不能让模型靠想象描述图片** |
| 文本里出现 `[CQ:...]` 之类的乱码 | `messagePostFormat=string` | 同上 | 改成 `array` |
| WSL 重启后 QQ 不工作 | NapCat 用 screen 跑，重启不会自动回来 | `screen -ls` | 用 `systemctl --user enable --now qq-napcat` 代替 screen |
| `qq-bot` 每 10 秒重启一次刷日志 | `Restart=always` + 启动就失败（常见：`qq.env` 不存在） | `journalctl --user -u qq-bot -n 20` | 跑 `wsl/install-qq.sh`；或先 `systemctl --user stop qq-bot` |

---

## 13. 回滚（只停 QQ，不动微信）

```bash
# 1) 最稳的一步：先急停（worker 立刻停手，不再发送任何消息）
touch ~/.local/state/qq-bot/STOP

# 2) 停 QQ 的两个单元（不 disable 也行，disable 是为了开机不再自动起）
systemctl --user stop qq-bot
systemctl --user disable qq-bot
systemctl --user stop qq-napcat 2>/dev/null || true
systemctl --user disable qq-napcat 2>/dev/null || true

# 3) 若 NapCat 是 screen 跑的，也停掉
screen -S napcat -X quit 2>/dev/null || true

# 4) 确认微信完全没受影响（这三行必须还是 active/running）
systemctl --user is-active wechat-stack wechat-bot wechat-soak
python3 /mnt/d/AgentPrograms/wechat-bot/wsl/health.py     # 微信的体检，ok:true
```

**彻底清理（可选，仍然只碰 QQ）**：删 `~/.local/state/qq-bot`、`~/.config/qq-bot`、
`~/.local/share/qq-bot`（venv）、`~/.config/systemd/user/qq-*.service` 后 `daemon-reload`；
NapCat 本体在 `~/Napcat`，要删自己删。**微信的 `~/.local/state/wechat-bot/` 一个字都别动。**

---

## 14. 文件清单（QQ 侧）

| 文件 | 作用 | owner |
|---|---|---|
| `qq/core/INTERFACES.md` | 接口契约 v1（冻结）：字段、优先级、配置 schema | lead |
| `qq/core/*.py` | 平台无关的同步实现（envelope/policy/bridge/media/store/service/worker/config） | qq-core |
| `qq/bot.py`、`qq/plugins/qq_chat.py` | NoneBot2 接入（只解析 + submit，永不 await 模型） | qq-nonebot |
| `qq/config/qq.example.json`、`qq/requirements.txt` | 示例配置与依赖清单 | qq-nonebot |
| `wsl/install-qq.sh` | 幂等安装（venv/依赖/目录/配置/单元；不启动、不 sudo） | qq-deploy |
| `wsl/qq-bot.service` | NoneBot 常驻单元（无 DISPLAY，不依赖微信） | qq-deploy |
| `wsl/qq-napcat.service` | NapCat 常驻单元（**可选**，替代 screen） | qq-deploy |
| `wsl/qq-health.py` | 一行 JSON 体检（进程/systemd/心跳/登录/WS/队列/STOP） | qq-deploy |
| `wsl/qq-acceptance.py` | 离线验收表 | qq-deploy |
| `test_qq_deploy.py` | 上面这些脚本的自测 | qq-deploy |
| `wsl/qq-e2e-fake-napcat.py` | 假 NapCat：不登录 QQ 也能验通"事件→策略→队列→模型→安全闸→send_msg→台账" | lead |
| `wsl/qq-e2e-live-check.sh` | 一键 4 场景端到端回归（私聊 / 群里不 @ / 群里真 @ / 同 id 重投） | lead |
| `docs/QQ.md` | 本文件 | qq-deploy |

**一句话记住**：QQ 是独立的第二套链路，微信链路一个字不改；
先过闸门再放开，出问题就 `touch STOP`。
