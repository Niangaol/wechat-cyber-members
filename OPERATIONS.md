# 年糕.Agent 微信机器人 · 运维手册

> 最后更新：2026-10-17 02:20（实机在跑，过夜烤机进行中）。所有命令都可以直接复制粘贴。

## 一、它现在在干什么

| 能力 | 状态 |
|---|---|
| 群聊自动回复（白名单制） | ✅ 实机验证：Agent 聊天测试群 5 条真实回复，单条 6.0–8.8s（改造前 9–14s） |
| 私聊自动回复（黑名单制） | ⏳ 代码就绪、标题核验通过，还没等到一条真实的入站新消息 |
| 分级入队 / 额度池 / 排队发送 | ✅ 群@ 和私信高优先，普通群聊降级；额度 6000/5h、70000/1d |
| 每会话每小时回复上限 | ✅ `max_replies_per_hour=30`，到顶消息留队列不丢（防机器人互刷） |
| 临时故障重试 | ✅ 模型抖动/超时 → 重试 `max_send_retries=2` 次（退避 5s），日志 `queue_item_retry` |
| 图片上下文封顶 | ✅ `reply_image_limit=2`（只挂最新两张；实测挂 6 张要多花 8 秒） |
| 界面卡住自愈 | ✅ 会话看不成就把微信拉前台 + Esc 关浮层（120 秒最多一次），日志 `ui_recover` |
| 分会话记忆 + 自学习 | ✅ profiles/记忆表在跑（每 20 条样本触发一次学习） |
| RSSHub 热榜注入 | ✅ hot_items 表有数据，需要搜索的提问会带上 |
| 联网搜索（agent 调 tool） | ✅ 实机验收（2026-10-18）：模型自己决定要不要搜，一次回复最多一次；不搜 1.8s、搜 5–8.5s |
| 图片/表情发送 | ⛔ 未启用（`allow_images/allow_stickers=false`） |
| 朋友圈发布 | ⛔ 代码链路已加固，但微信客户端配图上传报 `Photos not sent.`，暂停 |
| 朋友圈点赞/评论 | ⛔ 未启用（`interact.enabled=false`） |

## 联网搜索（Tavily）怎么配 / 怎么验 / 怎么关

**它是什么**：联网搜索是一个**交给模型自己调用的 tool**（原生 function calling）。
回复分两段：第一段带 `web_search` 工具，模型要么直接回话、要么只回一个 tool_call；
真调了工具就去打 Tavily 的 `POST https://api.tavily.com/search`，把结果以 `role:tool` 消息回灌，
**第二段请求不再带工具**——这就是"一次回复最多查一次"的硬保证。执行器自己还有第二道闸
（`resident.search_tool`），模型一口气吐多个 tool_call 也只放行第一个。
参数在 `config/resident.json → web_search`。

**RSSHub 热榜没变**：它仍是本地缓存、免费，只在 `needs_search` 正则命中时塞进上下文，
和工具是两回事（热榜给"最近大家在聊什么"，工具给"去网上查这个事实"）。

**先说钱**（Tavily 官方文档 2026-10-18 版）：免费额度 **1000 credits/月**，
`search_depth=basic` **1 credit/次**、`advanced` **2 credits/次**；超出后按 $0.008/credit。
按现在的用法（缓存 10 分钟 + 每小时上限 30 + 只在时效性提问上触发），免费额度够用。

**实测记录（2026-10-18）**：`国产手柄 推荐` → HTTP 200，3.16s，返回 5 条真实结果
（京东排行榜 / B站横评 / Chiphell / YouTube），全部通过安全闸。

### 第 1 步：确认 key 在 WSL 里能用

Windows 用户级环境变量里已有 `TAVILY_API_KEY`，但**服务跑在 WSL 里，看不到 Windows 的环境变量**，
要单独给 WSL 侧的运行时凭据写一份（命令里不出现 key 明文，粘贴时不回显）：

```bash
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'python3 - <<PY
import getpass, json, os
k = getpass.getpass("粘贴 Tavily key 后回车（不回显）: ").strip()
p = os.path.expanduser("~/.local/state/wechat-bot/credentials.json")
d = json.load(open(p)) if os.path.exists(p) else {}
d["tavily_api_key"] = k
json.dump(d, open(p, "w"), ensure_ascii=False, indent=2)
os.chmod(p, 0o600)
print("已写入，字段:", sorted(d))
PY'
```

### 第 2 步：实测（只打一次搜索 API，**不碰微信界面**）

```bash
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'cd /mnt/d/AgentPrograms/wechat-bot && python3 wsl/check-search.py "国产手柄 推荐"'
```

会报：用的哪个 provider、端点、key 从哪来、耗时、过滤前后条数、每条标题/链接/摘要。
- 看到 `认证失败(401)` → key 写错了
- 看到 `HTTP 432/433` 之类 → 免费额度用完或超了付费上限，响应体会带出来
- 看到"过滤后 0 条"但 `last_error` 为空 → 结果全被安全黑名单筛掉了（有意为之，不是 bug）

### 线上怎么确认"它真的搜了"

每次回复都会把这两个数写进 `~/.local/state/wechat-bot/status.json`：
- `search_calls`：这次回复模型调了几次搜索工具（**只可能是 0 或 1**，是"最多一次"的现场证据）
- `search_hits`：搜索结果过了安全闸、真正回灌给模型的条数

逐条明细在 `ledger.sqlite` 的 `web_search_calls` 表（query / ok / items / error / provider）。
日志里能看到 `web_search_extra_call_ignored`（模型想调第二次被拦下）。

### 第 3 步：重启机器人让它生效

```bash
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'systemctl --user restart wechat-bot && sleep 3 && journalctl --user -u wechat-bot -n 20 --no-pager'
```

### 怎么切 provider / 怎么调 / 怎么关

- **切回 DeepSeek**：`web_search.provider` 改成 `"deepseek"`，其余不用动——
  两个 provider 的出厂默认（端点、key 名、score 门槛）都写在代码里，各自的子块也能覆盖。
  （DeepSeek 那把 key 实测 402 余额不足，切过去要先充值。）
- **别切错分数门槛**：Tavily 的 `score` 是 **0~1**、DeepSeek 的 `rerank_score` 是 **0~3**。
  两个阈值分别写在 `tavily.min_score`（默认 0.3）和 `deepseek.min_score`（默认 1.2）里，
  **互相抄会让结果要么全丢要么全留**。
- **关掉**：`web_search.enabled = false`（改完重启服务；热榜兜底照常）
- **别太频繁**：`max_per_hour`（默认 30）是每小时真实请求上限；`cache_ttl`（默认 600 秒）
  让同一句话重复问只花一次 credit
- **连续失败自动停**：`breaker_after=3` 次失败后暂停 `breaker_seconds=600` 秒，
  期间静默走热榜（401/402 这类问题重试也没用，但不该每条消息都白等一次网络）
- **加 Tavily 其它参数**：`web_search.extra_body` 里的键会被原样合并进请求体，
  例如 `{"topic": "news", "days": 3}` 或 `{"include_answer": true}`
- **让更多提问触发搜索**：`src/search.py` 里的 `TRIGGER` 正则现在只认时效性词
  （最新/热搜/今天/新闻…）。想让它连"多少钱 / 哪个好 / 推荐"也去查，把词加进那条正则
  （改的是触发条件，**会让搜索次数明显变多**）

## 朋友圈发布：选项 A 操作手册（等你说"走 A"）

**前置条件（都已就绪）**
- 草稿：`moments id=3`（自我介绍，state=DRAFT，配图已挂）
- 物料：[outbox/首条朋友圈.md](outbox/首条朋友圈.md) + `outbox/first-post-image.jpg`（1080×1080 / 142KB，上传友好）
- 人审令牌：`~/.local/state/wechat-bot/APPROVE_MOMENT`（存在才允许发，且**摘要必须与草稿正文+配图完全一致**）
  - 已实测：令牌绑定内容摘要——改一个字（或换配图）令牌立刻失效，"批准过的旧稿"永远不能拿来发新稿 ✓
  - 当前状态：id=3 已重新批准、四个闸门 dry_run 全部通过（下面第 4 步就是真发）
- 总闸：`config/resident.json → automation.allow_moments`（当前 false，走 A 时我会打开）

**步骤（我来执行，你只需说"走 A"）**
1. 重启栈：`systemctl --user restart wechat-stack` → 微信客户端会重新拉起
2. 核验登录：`DISPLAY=:99 python3 wsl/health.py`，`wechat` 必须是 `main 1021x740`（若是 `logged-out 292x396` 就需要**你扫码**）
3. 先做一次只读侦察：打开朋友圈面板截图确认图标/坐标还对得上（`config/moments-coords.json` 的 `calibrated_at` 是 2026-10-16T17:52，客户端重启后可能变化）
4. 打开 `allow_moments`，用 APPROVE_MOMENT 令牌走一次发布；**第一条永远只发文字**（配图另行尝试），因为客户端配图上传报 `Photos not sent.`
5. 验证：`SELECT id,state,published FROM moments` → 成功是 `PUBLISHED`；失败会停在 DRAFT 且**绝不自动重试**（草稿保留，不谎报成功）

**回滚**
- 任何时候出问题：删掉 APPROVE_MOMENT、关掉 allow_moments，草稿原样留着
- 紧急全停：`touch ~/.local/state/wechat-bot/STOP`

**如果配图仍然失败**
- 不再折腾客户端 → 走选项 B：把 `outbox/first-post-image.jpg` 传手机、正文复制 `outbox/首条朋友圈.md`，你手动发

## 出事会主动告诉你（Windows 通知）

看门狗每 10 分钟检查一次，遇到**只有你才能解决**的情况会弹 Windows 通知：

| 情况 | 通知 | 你要做什么 |
| --- | --- | --- |
| 微信掉登录（窗口变 292x396） | 「微信掉登录了，年糕.Agent 已暂停」 | 打开 http://127.0.0.1:6080/vnc.html 重新扫码 |
| 机器人服务起不来 | 「年糕.Agent 服务没起来」 | 看 `journalctl --user -u wechat-bot -n 50` |
| 心跳卡住 >180s | 「年糕.Agent 心跳卡住了」 | 同上；必要时 `systemctl --user restart wechat-bot` |

- 同类问题 **30 分钟只提醒一次**；你手动 `touch STOP` 急停时**不会**被通知打扰
- 自己测一下通知能不能弹：
  ```bash
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'D:\AgentPrograms\wechat-bot\windows\watchdog.ps1' -TestToast
  ```
- 告警记录在 `logs/watchdog-alert.json`，健康流水在 `logs/watchdog.log`

## 掉登录怎么恢复（一条命令判断走到哪一步）

```bash
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'cd /mnt/d/AgentPrograms/wechat-bot && DISPLAY=:99 python3 wsl/relogin.py'
```

它会看客户端现在停在哪一步并告诉你怎么办（停在登录窗时，会替你点一下 Log In）：

| 屏幕状态 | 脚本行为 | 你要做的 |
| --- | --- | --- |
| 主窗口 1021x740 | 报"已登录" | 什么都不用做 |
| 登录窗（有 Log In 绿按钮） | 自动点 Log In | 手机微信里点「确认登录」 |
| **二维码页（Scan to log in）** | 报"请扫码" | 电脑上开 http://127.0.0.1:6080/vnc.html ，手机微信「+ → 扫一扫」扫屏幕上的二维码（失效就点一下二维码刷新）|
| 认不出的界面 | 什么都不点，报出来 | 开虚拟屏人工看一眼 |

手机"确认登录"的提示有有效期，过期后会**退回二维码页**（2026-10-17 就发生了这件事）。
两种情况都只需要一次手机操作，**不需要重新输账号**。

## ⚠️ 一条铁律：别在无人值守时重启 `wechat-stack`

`systemctl --user restart wechat-stack` = **重新拉起微信客户端** → 客户端可能回到登录窗、
要求**手机确认登录**（2026-10-17 凌晨我就是这么把机器人按停的 ✗）。深夜/无人时一律不做。

- 重启 `wechat-bot` **是安全的**（不影响客户端登录）——部署代码改完重启它就行
- 真要重启 stack：人在场，且准备好手机确认（一般不需要重新扫码）
- `wsl/install-services.sh` 已改成默认**不** restart stack，必须显式 `--with-stack`
- 客户端停在登录窗时，机器人会自己暂停（`wechat=logged-out 292x396`、`observed_chats 0/2`），
  手机确认后主窗口恢复 1021x740，**它会自动继续，不用重启服务**

## 云端模型切换（MiMo-V2.6-Flash / OpenCode Go）与回滚

配置里同时留着两套：`step_plan`（当前在跑）和 `model`（新端点，`enabled:false`）。
**只有 `model.enabled=true` 才会切过去**；改回 false 立刻回到旧端点，不需要改别的。

### 第 1 步：把密钥写进运行时凭据（**你自己在终端里跑，别粘到对话里**）

```bash
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'python3 - <<PY
import getpass, json, os
k = getpass.getpass("粘贴 OpenCode Go 密钥后回车（不回显）: ").strip()
p = os.path.expanduser("~/.local/state/wechat-bot/credentials.json")
d = json.load(open(p)) if os.path.exists(p) else {}
d["opencode_api_key"] = k
json.dump(d, open(p, "w"), ensure_ascii=False, indent=2)
os.chmod(p, 0o600)
print("已写入，字段:", sorted(d))
PY'
```

### 第 2 步：实测新端点（只调模型，**不碰微信界面**，随时可安全跑）

```bash
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'cd /mnt/d/AgentPrograms/wechat-bot && python3 wsl/check-model.py'
```

会逐项报：文本调用 / 真实 usage / max_tokens 截断行为 / **图片输入（data URL）**。
图片那项如果不通过，说明这个端点当前不能读图：**图片理解继续走本机 OCR + 旧视觉端点**，
并把"图片能力降级"写进状态，而不是悄悄换一家付费模型。

### 第 3 步：切换并重启（只重启机器人，不碰微信）

```bash
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'cd /mnt/d/AgentPrograms/wechat-bot && python3 -c "
import json, pathlib
p = pathlib.Path(\"config/resident.json\"); c = json.loads(p.read_text())
c[\"model\"][\"enabled\"] = True
p.write_text(json.dumps(c, ensure_ascii=False, indent=2) + chr(10))
print(\"model.enabled =\", json.loads(p.read_text())[\"model\"][\"enabled\"])"'
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'systemctl --user restart wechat-bot'
```

### 回滚（30 秒）

把 `model.enabled` 改回 `false` 再 `systemctl --user restart wechat-bot` 即可。
旧端点配置（`step_plan`）一直留在文件里，不需要重新填密钥。

### 失败时的自动行为（不用你盯着）

- **401/403**：立即停用该 provider 并停止调用（重试只会锁死账号），状态里出现 `model.disabled`
- **429**：尊重服务端的 `Retry-After`
- **5xx / 网络 / 超时**：指数退避 + 抖动，最多 2 次重试
- **连续 3 次失败**：熔断 60 秒，期间不再打出去（防风暴）
- 每次调用（成功/失败）都写一行真实 usage 到 `model_calls` 表

## 一条命令验收（上线自检）

```bash
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'cd /mnt/d/AgentPrograms/wechat-bot && python3 wsl/acceptance.py'
# 连 370 项离线单元测试一起跑（约 20 秒）
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'cd /mnt/d/AgentPrograms/wechat-bot && python3 wsl/acceptance.py --tests'
```

输出一张表，逐项 ✅/❌，退出码 0 = 全过：

| 检查项 | 说明 |
| --- | --- |
| 环境：两个 systemd 服务 | 服务不是 active 就报出来 |
| 环境：健康 JSON | 掉登录/瞎了/心跳卡住都会红 |
| 朋友圈：发布四道闸门 | dry_run，不碰 UI（含令牌有效性） |
| 互动：白名单/隐私/频率 | 5 个离线场景 |
| 朋友圈：草稿节奏/选题/安全闸 | 2–3 天节奏、选题白名单、不安全文案不落库 |
| 安全：隐私判据统一 | 手机号/密钥在私聊与朋友圈两条路都被拦 |
| 离线单元测试（--tests） | 370 项 + "0 外部调用" |

## 一条命令烤机（看"能不能一直活着"）

```bash
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'bash /mnt/d/AgentPrograms/wechat-bot/wsl/soak-start.sh'
```

烤机现在是 **systemd 用户服务** `wechat-soak.service`（`Restart=always` + 开机自启），
所以"监控自己挂了没人知道"这件事不会发生：实测 SIGKILL 后 10 秒自动拉起，样本续写不丢窗口。

```bash
systemctl --user status wechat-soak        # 看它在不在跑
journalctl --user -u wechat-soak -n 20     # 看它的异常记录
```

手动跑一次（不装服务）：默认每 30 秒采一次、跑 90 分钟，样本写 `~/.local/state/wechat-bot/soak-<tag>.jsonl`，
异常（服务掉线 / STOP / 心跳断档 >60s / 队列堆积 >5 / 会话观察掉到 0）会打到 `soak-<tag>.log`。
想换参数：`SOAK_INTERVAL=10 SOAK_DURATION=600 SOAK_TAG=quick` 再调脚本。

## 二、一条命令体检

```bash
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'DISPLAY=:99 python3 /mnt/d/AgentPrograms/wechat-bot/wsl/health.py'
```

输出一行 JSON，`ok:true` 才算健康。关键字段：

- `wechat-bot` / `wechat-stack`：两个 systemd 服务必须是 `active`
- `heartbeat_age_s`：主循环心跳，> 90 秒说明卡住了
- `wechat`：`main 1021x740` 正常；`logged-out 292x396` = 掉登录了，要重新登录
- `chats_observed`：`2/2` 表示两个会话都被看见并核验了标题
- `stop_file`：`true` 说明被安全暂停了（见下）

## 三、常用操作

```bash
# 看实时日志（回复、计时、报错都在这里）
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'journalctl --user -u wechat-bot -f'

# 重启机器人（改了 src/*.py 之后必须重启才生效）
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'systemctl --user restart wechat-bot'

# 重启整套虚拟屏 + 微信 + VNC（微信窗口错乱/崩了时用）
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'systemctl --user restart wechat-stack'

# 急停 / 恢复（STOP 文件是互锁，存在就绝对不发消息）
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'touch ~/.local/state/wechat-bot/STOP'
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'rm -f ~/.local/state/wechat-bot/STOP'
```

## 四、常驻是怎么保住的（三层）

1. **常驻 WSL 客户端**：`WeChatBotKeepAlive`（登录时跑 [wsl-keepalive.vbs](windows/wsl-keepalive.vbs)），循环挂一个 `wsl.exe ... sleep 2147483`。没有它，WSL2 会在最后一个客户端退出约 60 秒后**关掉整台虚拟机**，机器人一起死（这是之前"看着常驻其实一直掉线"的根因）。
2. **看门狗**：`WeChatBotWatchdog` 计划任务，每 10 分钟跑一次 [watchdog.ps1](windows/watchdog.ps1)：补齐常驻客户端（多余的会裁到 1 个）、拉起两个 systemd 服务、把一行健康 JSON 追加到 `logs/watchdog.log`。
3. **`.wslconfig`**：`instanceIdleTimeout=-1` + `vmIdleTimeout=-1`（需要 `wsl --shutdown` 后生效），彻底关掉空闲自动关机。

重新注册计划任务（换机器/误删时）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File D:\AgentPrograms\wechat-bot\windows\register-keepalive-task.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File D:\AgentPrograms\wechat-bot\windows\register-watchdog-task.ps1
```

## 五、配置在哪

`config/resident.json`：

- `group_whitelist` / `direct_whitelist` / `direct_blacklist`：谁能被回、谁绝对不回（群聊只有白名单里的群会被看）
- `watch_chats`：当前盯的会话（现在两个：Agent 聊天测试群、很帅的年糕）
- `poll_seconds` / `debounce_seconds`：检测节奏（现在 3s / 1s）
- `min_reply_seconds`：同一个会话两条回复的最小间隔（现在 8s）
- `concurrency.max_sends_per_cycle`：一轮最多发几条（现在 2）
- `limits.window_5h` / `window_1d`：额度池上限（模型调用次数）
- `automation.allow_images` / `allow_stickers` / `allow_moments`：三个总闸，默认全关

改完不用重启（主循环每轮重读配置），但 `automation.enabled=false` 会立刻停止一切发送。

## 六、朋友圈怎么发（等客户端修好后）

```bash
# 1) 看草稿 + 当前批准状态
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'cd /mnt/d/AgentPrograms/wechat-bot && python3 wsl/moment-release.py --list'

# 2) 人工批准某条草稿（写 APPROVE_MOMENT 令牌，绑定内容摘要）
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'cd /mnt/d/AgentPrograms/wechat-bot && python3 wsl/moment-release.py --approve 3'

# 3) 打开朋友圈总闸（allow_moments=true），常驻机器人下一轮就会发；发完记得关回去
```

注意：微信 Linux 客户端目前发朋友圈配图会报 `Photos not sent.`（纯文字动态在这版客户端没有入口，必须先选图进编辑页）。**这是客户端问题，不是链路问题**：链路已经跑到点 Post + 判成功，且判据已加固（编辑页必须退出 + 9 秒内无失败红条）。

## 七、出问题先看这三处

1. `health.py` 的 `ok` 和 `wechat` 字段：掉登录 → 用浏览器打开 <http://127.0.0.1:6080/vnc.html> 手动扫码/点确认。
2. `journalctl --user -u wechat-bot -n 50`：找 `cycle_failed` / `reply_timing` / `moment_*`。
3. `logs/watchdog.log`：看虚拟机和服务有没有被自动救回来。

常见现象对照：

| 现象 | 大概率原因 | 处理 |
|---|---|---|
| 完全不回复 | STOP 文件 / 掉登录 / 额度耗尽 | 看 `health.py`，删 STOP，重新登录 |
| 只回一个群 | 另一个会话标题核验失败 | 看日志 `paused_chat_switch`，重启 `wechat-stack` |
| 回复很慢 | 模型调用慢（看 `reply_timing model=`） | 属正常波动；检测延迟看 `cycle_timing observe=` |
| 服务反复重启 | WSL 被关 | 看 `logs/watchdog.log`，确认常驻客户端在 |

## 上线时间排班（早上 8 点 – 晚上 10 点）

2026-10-18 起，机器人**只在这个窗口内上线**：22:00 整下班、08:00 整上班。
窗口外不观察、不回复、不发朋友圈、不互动——整个 cycle 直接跳过。

### 两层保障（故意做两份，互为兜底）

| 层 | 实现 | 作用 |
| --- | --- | --- |
| 进程内闸门 | `resident.py` 的 `online_now()` + `_cycle` 开头 | 到点就不干活；就算有人手动 `systemctl --user start wechat-bot` 也不会在窗外说话 |
| systemd 定时器 | `wechat-bot-start.timer` / `wechat-bot-stop.timer` | 到点起停服务，夜里把 CPU/内存还回来 |

`wechat-bot.service` 已 **disable**（开机不再自启），起停完全交给定时器；
`wechat-stack`（虚拟屏 + 微信 + VNC）保持常驻，**不动它**——停掉微信可能要重新扫码。

### 改作息（只改两个数，两边同步）

```bash
# ① 定时器那边
vi /mnt/d/AgentPrograms/wechat-bot/wsl/bot-schedule.sh   # 改 START_HOUR / STOP_HOUR

# ② 进程内闸门那边（config/resident.json 的 online_window.start_hour / stop_hour）

# ③ 生效
cp /mnt/d/AgentPrograms/wechat-bot/wsl/wechat-bot-{start,stop}.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user restart wechat-bot-start.timer wechat-bot-stop.timer
```

> 两边必须是同一套时间。定时器负责"省资源"，进程内闸门负责"绝不窗外说话"，
> 改了一个忘了另一个会出现"服务在跑但一整晚不说话"的怪状态。

### 到点下班长什么样（不是坏了）

```bash
DISPLAY=:99 python3 wsl/health.py
# wechat-bot: inactive、scheduled_offline: true、next_start: 明天 08:00、ok: true
```

停机时 `bot-schedule.sh` 会写 `~/.local/state/wechat-bot/scheduled-offline.json` 作标记，
health.py 看到它就报"到点下班"而不是 `ok:false`——免得半夜误判成机器人挂了。
窗口内启动时标记自动清除。

### 手动插队（临时让它说两句 / 立刻下班）

```bash
systemctl --user start wechat-bot     # 窗外也能拉起来，但进程内闸门照样不让它说话
systemctl --user stop wechat-bot      # 立刻下班（记得之后 start 回来）
```

