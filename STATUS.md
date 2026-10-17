# 年糕.Agent 状态速览

> 一页看完：现在什么状态、需要你做什么、已经验过什么。
> 详细版：[VERIFICATION.md](VERIFICATION.md)（逐项证据）· [OPERATIONS.md](OPERATIONS.md)（运维手册）
> 更新：2026-10-17 12:48
> 当前模型：`step-3.7-flash` + `reasoning_effort=low`（用户最新确认）。真实提示词单独生成测试三例 1.8–1.9s，不含轮询/OCR/发送；机器人服务已重启为 active。下方历史验收记录不代表当前配置。

## 一句话

当前为群聊为主、私聊开启；回复模型采用 StepFun `step-3.7-flash` + low。三个群仍按原白名单策略；私聊现在自动发现新好友，在通讯录核验昵称与微信号后加入监听，黑名单仍生效。当前已自动登记人在月球有点冷、李想26计科、豆包、阿比盖尔 威廉姆斯，4位均已有真实自动回复，最近一轮9/9会话观察成功、队列已清空。详见[自动好友监听](docs/自动好友监听.md)。完整端到端延迟仍受轮询、OCR 与发送核验影响。

## 新好友自动监听（2026-10-17）

- `direct_auto_discover=true`，扫描间隔60秒，发现阶段纯本地OCR，不调用模型。
- 已通过482项离线测试；覆盖群隔离、黑名单即时撤权、首条私信入队、防重复及完整标题核验。
- 实机：人在月球有点冷12:44:07收到自动回复；李想26计科12:47:28、豆包12:47:37收到自动回复。阿比盖尔 威廉姆斯12:49:24收到自动回复；12:49轮询9/9成功，黑名单与群白名单均继续生效。
- 同时修复侧栏变宽导致头像误判/空输入框误报草稿，中文标题OCR及群预览抢占私聊定位。
- 未重启微信栈；仅部署重启回复服务。一次服务重启等待旧轮次超时后由systemd终止旧进程并成功拉起，微信登录保持，待发队列保留。

## 「人机」群验收：✅ 通过（2026-10-17 10:26）

```
10:24:49  很帅的年糕  qq 做机器人好方便啊            ← 普通消息
10:24:49  很帅的年糕  @年糕 Agent 你说是不是          ← @
10:24:49  很帅的年糕  @年糕 Agent 对不对啊            ← @
10:25:45  reply_timing chat=group:人机 priority=group_at model=36.2s send=3.9s
          → 机器人回：方便是方便，但动脑的部分还是逃不掉——比如现在，本糕就被你@得不得不思考人生。
10:26:10  很帅的年糕  666连我都敢攻击了              ← 普通消息
          group_plain_ignored reason=plain_not_addressed  → **没有回**（符合「选择性接话」）
```

上线前还抓到并修掉一个会让正式群**一条消息都读不出来**的 bug（群聊气泡方向判定写死了私聊坐标），详见 [VERIFICATION.md](VERIFICATION.md) 的「上线改造」节。

### 模型最终选择（2026-10-17 10:37 定案）

MiMo-V2.6-Flash（太贵）→ LongCat 2.5 Preview Free（免费但慢、且限时免费）→ **StepFun `step-5-preview` + medium 思考**。

| 端点 | 文本 | 读图 | 备注 |
| --- | --- | --- | --- |
| OpenCode Go · LongCat 免费档 | 6.9–8.6s（真实回复那次 36.2s） | 11.5s | 限时免费，波动大 |
| **StepFun · step-5-preview（当前）** | **1.7s** | **2.1s** | 用户账号，稳定 |

回复预算相应调大（无图 2200 / 带图 2800 tokens）：推理模型会先把思考写进 completion，小预算会被思考吃光、`finish_reason=length`。
想再试 OpenCode Go：`model.enabled` 改回 `true`，配置原样留着。

### 可选（不急）

- **朋友圈首帖 A/B/C**：物料已备齐（[outbox/first-post-image.jpg](outbox/first-post-image.jpg) + [outbox/首条朋友圈.md](outbox/首条朋友圈.md)，草稿 id=3 已挂图、四道闸门 dry_run 全过）
- **小红点方案**：现在被监控的会话红点会被点掉
- **表情包发送 / 朋友圈点赞评论**：执行侧还没实现（图片发送已实机验证可用）

## 现在的形态（配置即事实）

| 项 | 值 |
| --- | --- |
| 群聊 | 「Agent 聊天测试群」（`all`，测试用）+ **「人机」**（`idle`：@ 必回、喊名字、刚回过话的追问，**队列空闲时闲聊也接一句**；120 秒冷却、6 次/小时）+ **「Vibe AI Lab 招新交流群」**（214 人大群，`selective`：只接 @ / 喊名字 / 追问；180 秒冷却、4 次/小时，普通闲聊不回）|
| 私聊 | **开启，但以群聊为主**（`direct_enabled=true`，白名单：很帅的年糕、Deepseek）。优先级 **群 @(0) > 私信(1) > 群闲聊(2)**；私信轮到自己时若队列里还有群 @ 在等，会主动让位回队列（最多 3 次）。想关掉改 `false` |
| 模型 | **StepFun StepPlan · `step-3.7-flash` + low**；文本/usage/截断拒绝/读图四项端点测试通过，三例真实提示词生成耗时 1.8–1.9s（不含发送）。|
| 回复节奏 | 两条回复最小间隔 `min_reply_seconds=3`（原 8）；轮询 `poll_seconds=2`；上下文只带最近 8 轮 + 12 条时间线（原 12+20，直接决定首字延迟）|
| 回退 | `model.enabled=true` → 切回 OpenCode Go（LongCat/MiMo 配置原样留着）；换模型只动 `config/resident.json` 一行 |

## 现在的体检（下面这条随时可重跑，别信快照）

```bash
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'cd /mnt/d/AgentPrograms/wechat-bot && DISPLAY=:99 python3 wsl/health.py'
```

## 已经过实测的能力（都有证据，不是"写了代码"）

- **群聊自动回复**：多条真实回复；换 LongCat 后实测 6.9–8.6s/条
- **读图**：LongCat（data URL）实测描述准确；图片**发送**实机成功（含粘贴预览校验）
- **自愈**：SIGKILL 10 秒拉起；**卡死连续两轮 → 看门狗自动重启机器人**（2026-10-17 实机演练）
- **急停**：`touch STOP` 立刻停发、不丢消息；删掉自动恢复
- **主动告警**：掉登录 / 服务挂 / 心跳卡住 / 模型被停用或熔断 / "活着但瞎了"
- **防丢消息**：排队期间滚出视口的消息会**合并保留**，不再被新任务覆盖
- **抗提示注入**：索要密钥、冒充开发者、网页塞假指令、要求转账——四类全拒，零泄露
- **风格自学习 / 生图 / RSSHub 热榜 / 链接理解**：全部在位
- **测试**：408 项全绿，0 外部调用

## 常用命令

```bash
# 一键验收（8 项自检 + 408 项测试）
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'cd /mnt/d/AgentPrograms/wechat-bot && python3 wsl/acceptance.py --tests'

# 看它最近干了什么
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'journalctl --user -u wechat-bot -n 40 --no-pager | grep -E "reply_timing|observe_decision|group_plain_ignored|ui_unavailable"'

# 急停 / 恢复
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'touch ~/.local/state/wechat-bot/STOP'
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'rm -f ~/.local/state/wechat-bot/STOP'

# 掉登录后恢复（会告诉你是"已登录/登录窗/二维码页"）
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'cd /mnt/d/AgentPrograms/wechat-bot && DISPLAY=:99 python3 wsl/relogin.py'

# 模型实测 / 回滚（详见 OPERATIONS.md）
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'cd /mnt/d/AgentPrograms/wechat-bot && python3 wsl/check-model.py'
```
