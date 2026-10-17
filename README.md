# wechat-bot · 年糕.Agent 微信机器人

**一句话**：跑在 WSL 虚拟屏里的微信自动化机器人——**纯 UI 路线**（截图 + OCR + 键鼠），不 hook、不注入、不读聊天数据库。平时轮询全程本地零模型额度，**只有要写内容时才调大模型**（一次 1 单位）。

> **状态速览（2026-10-17）**：群聊自动回复 ✅ 实机验收（真实回复单条 6.0–8.8s）· 崩溃自愈/急停/主动告警 ✅ · 图片理解 ✅ · 私聊回复 ⏳ 等一条真实入站消息 · 朋友圈发布 ⛔ 暂停等拍板 · 表情发送 ⛔ 受阻
>
> **配套文档**：[STATUS.md](STATUS.md)（一页速览：现在什么状态、要你拍板什么）· [VERIFICATION.md](VERIFICATION.md)（上线验收清单：每项证据 + 复现命令）· [OPERATIONS.md](OPERATIONS.md)（运维手册：体检/急停/保活/故障对照）· [RESEARCH.md](RESEARCH.md)（UI 自动化路线调研与铁律）· 旧版 README 存档于 [docs/archive/](docs/archive/)

## 它能干什么

| 能力 | 状态 | 说明 |
|---|---|---|
| 群聊自动回复 | ✅ 实机验收 | 白名单制（`group_whitelist`）；@ 必回优先；测试群全量接话，正式群 selective 限流（120s 冷却、6 条/时） |
| 私聊自动回复 | ⏳ 待验收 | 黑名单制（`direct_policy`）；代码 + 标题核验就绪，只差一条真实入站消息 |
| 图片理解 | ✅ 实机验收 | 气泡裁图喂模型；看懂才接话，看不懂不硬编 |
| 分级队列 + 额度池 | ✅ | 群@(0) > 私信(1) > 群普通(2)；共用 6000/5h、70000/1d；撞限额自动排队+休息提醒 |
| 分会话记忆 + 风格自学习 | ✅ | 按 `chat_key` 隔离档案；每 20 条触发一次学习，敏感样本剔除 |
| RSSHub 热榜 | ✅ | 4/6 源可用，多实例故障转移，10 分钟缓存，回复时只补一个源不卡回复 |
| 链接阅读 | ✅ | 仅公网 HTTP(S)、DNS 防重绑定、剥 script、总预算 12s |
| 生图 | ✅ 实机验收 | 千问 qwen-image-2.1-turbo，OC 参考图人设（`config/assets/oc-reference.png`） |
| 本地 VLM 操作（UI-TARS） | ✅ 部署 | llama.cpp CUDA + UI-TARS-1.5-7B，RTX 5070 Ti，`127.0.0.1:8088` |
| 朋友圈草稿→人审→发布 | ⛔ 暂停 | 四道闸 + dry_run 链路已加固；客户端配图上传报 `Photos not sent.`，等拍板 A/B/C |
| 朋友圈点赞/评论 | ⛔ 关闭 | 决策官+评论家双 Agent 管道就绪，`interact.enabled=false`，缺好友名单 fail-closed |
| 表情发送 | ⛔ 受阻 | 微信 4.1.1.8 点不开表情面板，`send_sticker` 未标定拒绝执行 |
| 图片发送 | ⛔ 未启用 | 已验到预览一步（xclip→Ctrl+V），真实发送等人工批准 |

## 架构

```
Windows 宿主
 ├─ 计划任务：watchdog（每 10 分钟自愈 + Windows 通知）· keepalive（WSL 不掉电）
 └─ WSL2 Ubuntu-24.04（systemd 用户服务）
     ├─ wechat-stack.service
     │   ├─ Xvfb :99 虚拟屏 ←── 微信 Linux 4.1.1.8
     │   └─ x11vnc :5900 → websockify/noVNC → http://localhost:6080/vnc.html（扫码 / 人工查看）
     ├─ wechat-bot.service（src/resident.py 主循环）
     │   每 2s：截图 → 本地 tesseract OCR → 画面指纹比对 → 分级入队
     │   要写内容才调模型 → 安全闸 → 粘贴 → 回车（发送前强制标题核验）
     │   状态/账本/凭据：~/.local/state/wechat-bot/（600 权限）
     └─ 可选：llama-server（UI-TARS 本地 VLM, :8088）
```

**为什么这么绕**：微信官方 Linux 客户端没有任何自动化接口。纯 UI 路线牺牲一点速度，换来零注入风险、
微信更新不敏感、以及“它看到的就是你看到的”这种可验证性。代价与取舍见 [RESEARCH.md](RESEARCH.md)。

## 快速开始

前置依赖（WSL2 + systemd 已开启）：`Xvfb`、`x11vnc`、`noVNC/websockify`、`tesseract-ocr`（含 `chi_sim`）、
`imagemagick`（`import` 按窗口 ID 截图）、`xclip`/`xsel`（图片必须 xclip）、`xdotool`、Python3 + Pillow、
微信 Linux 4.1.1.8。模型密钥走环境变量或 `~/.local/state/wechat-bot/credentials.json`（600），不进仓库。

```bash
# 1) 安装 systemd 用户服务（栈 + 机器人），详见 wsl/install-services.sh 与 OPERATIONS.md
wsl -d Ubuntu-24.04 -- bash /mnt/d/AgentPrograms/wechat-bot/wsl/install-services.sh

# 2) 注册 Windows 侧保活（watchdog + keepalive 计划任务，脚本在 windows/）

# 3) 扫码登录：浏览器打开 http://localhost:6080/vnc.html → Connect → 手机微信扫一扫
#    （掉登录后跑 wsl/relogin.py 会告诉你卡在哪一步）

# 4) 一键验收：7 项自检 + 370 项离线测试，一张表看全
wsl -d Ubuntu-24.04 -- python3 /mnt/d/AgentPrograms/wechat-bot/wsl/acceptance.py --tests
```

## 日常操作

```bash
# 体检（一行 JSON，ok:true 即健康；exit 0）
wsl -d Ubuntu-24.04 -- python3 /mnt/d/AgentPrograms/wechat-bot/wsl/health.py

# 机器人状态快照
wsl -d Ubuntu-24.04 -- cat ~/.local/state/wechat-bot/status.json

# 最近干了什么
wsl -d Ubuntu-24.04 -- journalctl --user -u wechat-bot -n 30 --no-pager

# 急停 / 恢复（急停会把处理中的消息放回队列，不丢、不花额度）
wsl -d Ubuntu-24.04 -- touch ~/.local/state/wechat-bot/STOP
wsl -d Ubuntu-24.04 -- rm -f ~/.local/state/wechat-bot/STOP

# 彻底停 / 起
wsl -d Ubuntu-24.04 -- systemctl --user stop wechat-bot
wsl -d Ubuntu-24.04 -- systemctl --user start wechat-bot

# 看见微信（扫码 / 人肉排查）
#   浏览器打开 http://localhost:6080/vnc.html
```

看门狗会主动弹 Windows 通知（掉登录 / 服务挂 / 心跳卡 / “活着但瞎了”），同类 30 分钟一次；
自测：`powershell -File windows/watchdog.ps1 -TestToast`。

## 目录导览

```
wechat-bot/
 ├─ src/                 机器人本体（25 个模块，见下方模块地图）
 ├─ wsl/                 运维/标定/验收脚本 + systemd 单位（acceptance/health/relogin/soak…）
 ├─ windows/             Windows 计划任务：watchdog.ps1、register-*.ps1、wsl-keepalive.vbs
 ├─ config/              resident.json（全部配置）· persona.md（人设）· moments-coords.json（实测坐标）
 │   ├─ assets/          OC 参考图 + 外观描述（生图人设基准）
 │   └─ chat-anchors/    人工核实的会话标题像素锚点
 ├─ legacy/              旧版原型代码（已退役，留作参考）
 ├─ outbox/              朋友圈待发物料（正文 + 压缩配图）
 ├─ shots/ + 根目录 png  历史排查截图留痕（可清理）
 ├─ docs/archive/        旧版 README 存档
 ├─ test_*.py            30 个离线测试文件（零外网；计时器拦截真实子进程/网络/DNS）
 └─ STATUS / VERIFICATION / OPERATIONS / RESEARCH .md   四份活文档
```

## 模块地图（src/）

| 模块 | 职责 | 状态 |
|---|---|---|
| resident.py | 主循环：轮询→分级入队→处理→学习→朋友圈（最大模块） | 单测 |
| wechat_ui.py | 截屏/OCR/剪贴板/键盘发送；标题像素模板白名单；发送前读回校验 | 实测 |
| screen.py | X 窗口树查找 + ImageMagick import 按窗口 ID 截图 | 实测 |
| chat_anchors.py | 人工核实的姓名绑定像素锚点（列表定位 / 标题精确核验） | 单测 |
| chat_navigator.py | 会话列表 OCR 定位 + 切换 + 标题核验 + 坐标缓存 | 单测 |
| visual_parse.py | 本地头像行定位气泡（不让模型编坐标，无法确认就拒绝） | 单测 |
| model_api.py | 模型接入层：provider 解析/重试/熔断/真实用量记录 | 单测 |
| multimodal.py | StepPlan 视觉解析 + 回复组装（人设注入 + 安全边界） | 实测 |
| quota.py | 共用额度池 + 优先级队列 + 休息提醒 + 消息合并（防静默丢消息） | 实测 |
| memory.py | 按 chat_key 隔离记忆 + 每 20 条风格自学习 | 单测 |
| search.py | RSSHub 热榜缓存（多实例故障转移 + 空闲轮转） | 实测 |
| web_reader.py | 受限网页读取（公网/DNS 固定/剥 script/总预算） | 单测 |
| multimedia.py | 气泡截图按会话隔离存放（哈希目录名） | 单测 |
| output_safe.py | 确定性输出终闸（敏感词/变体/凭证/超长） | 单测 |
| moments.py | 朋友圈内容策划池（白名单选题 + 种子轮换） | 单测 |
| moments_safe.py | 朋友圈内容安全层（黑名单 + 白名单话题，公开内容红线） | 单测 |
| moments_publisher.py | 发布/点赞/评论执行器（Moments 独立窗口适配；未标定绝不瞎点） | 实测 |
| moment_release.py | 草稿人审令牌 + 发布前四道闸 + 状态回写（dry_run 自证） | 单测 |
| moments_collector.py | 朋友圈动态采集（滚动截图 + 本地 OCR + 去重入库） | 单测 |
| moment_interact.py | 互动管道：决策官 + 评论家双 Agent，缺名单 fail-closed | 单测 |
| calibrate.py | 登录后坐标标定（微信绿按钮/相机图标像素定位） | 单测 |
| imagegen.py | 千问生图（OC 参考图缩 512px base64 注入） | 实测 |
| dual_agent.py | 双 Agent 协作：UI-TARS 定位操作 + StepPlan 写内容 | 实测 |
| ui_lease.py | 协作式 UI 锁（flock 跨进程排他、同线程可重入、不删锁文件） | 单测 |

常用 wsl/ 脚本：`acceptance.py`（一键验收）· `health.py`（体检）· `relogin.py`（掉登录恢复）·
`readiness.py`（只读就绪核查）· `soak.py`（烤机采样）· `moment-release.py`（朋友圈草稿 CLI：list/approve/revoke/publish）·
`start-uitars-server.sh`（本地 VLM）。systemd 单位：`wechat-stack.service`、`wechat-bot.service`、`wechat-soak.service`。

## 核心机制（为什么这么设计）

- **零额度监控**：轮询/切换/截图/OCR/指纹比对全本地；只有回复、学习、朋友圈草稿、互动决策才花 API。
  纯监控模式模型调用数为 0，可以用 `status.json` 验证。
- **分级优先级 + 共用额度池**：群@ > 私信 > 群普通；每小时每会话回复上限 30 条防机器人互刷；
  撞限额自动发休息提醒并把任务挂起，额度恢复自动继续。
- **防发错窗（最大事故防线）**：每次发送前强制切到目标会话并 OCR 核验标题（辅以像素模板精确比对），
  不符一律拒发。这是从同类开源项目事故里提炼的铁律（见 RESEARCH.md）。
- **fail-closed 授权**：朋友圈没有“自动发布”开关——只有 `APPROVE_MOMENT` 人工令牌在位且内容摘要一致才发，
  改一个字令牌即失效；互动缺好友名单直接不跑不花额度；配置里没实现的开关在 `resident.json` 里显式标注“不生效”。
- **确定性安全闸双层**：输入侧热榜/链接内容过黑名单（含拆字/emoji/全角变体归一），输出侧终闸拦敏感词、
  疑似凭证、手机号、超长内容。关键词法不可能完备，靠系统提示 + 人工令牌兜底，不宣称语义安全。
- **活着且看得见**：看门狗区分“服务挂了”和“活着但瞎了”（进程在跑但一个会话都没看成）；
  掉登录静默退避（2s→30s、日志限流）；渲染瞬态（黑屏/空态）跳过本轮不计入连续异常，
  避免“微信抽风三次把自己吓停”。
- **协作式 UI 锁**：常驻主循环、朋友圈发布、互动 CLI 共用一把 flock 锁，忙碌时互相让路，
  防止两条流程同时抢虚拟屏（不约束人手操作和外部脚本）。

## 安全边界（写死的）

- 不读聊天数据库、不 hook、不注入（纯 UI 路线）
- 朋友圈内容/评论不碰热搜（公开平台风险不可控），只走白名单选题池
- 朋友圈发布没有“自动”开关：只有人工令牌 + 坐标已标定才会发，令牌随时可 `--revoke`；提交不确定时留占位禁止重发
- 凭证只在 WSL 私有目录 `~/.local/state/wechat-bot/credentials.json`（600 权限），不进项目、不进日志
- 抗提示注入实测：索要密钥、冒充开发者、网页藏指令、要求转账——四类全拒

## 测试

```bash
# 全量离线测试（30 个文件、370 项；计时器拦截真实子进程/网络/DNS，业务代码吞异常也会被抓）
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/d/AgentPrograms/wechat-bot && python3 -m unittest discover -p 'test_*.py'"

# 一键验收 = 7 项基础设施自检 + 上述测试，一张表
wsl -d Ubuntu-24.04 -- python3 /mnt/d/AgentPrograms/wechat-bot/wsl/acceptance.py --tests
```

测试通过 ≠ 真实微信链路通过。凡是标 ⏳/⛔ 的能力，都以 VERIFICATION.md 里的实机证据为准，
不靠单测绿灯宣称可用。

## 已知限制

- **被监控会话的小红点会被消掉**：纯 UI 路线必须点开会话才能读消息，这是路线固有代价；
  “徽标优先”替代方案已在 STATUS.md 待拍板（能保红点，空闲轮更快，最坏发现延迟约 40s）。
- 只覆盖**可见**会话列表：同名会话、字体/缩放/主题变化需重新核实，无新私聊自动发现。
- 表情面板在 4.1.1.8 上打不开（`send_sticker` 拒绝执行）；朋友圈配图上传报 `Photos not sent.`（文字发布未受影响）。
- 群聊普通消息的 selective 接话靠本地筛选，不调模型；未登记的正式群按最保守的 at_only。
- 关键词黑名单不可能完备，borderline 内容仍可能通过，属已知取舍。

## 待办（都需要人拍板，详见 STATUS.md）

1. **私聊验收**：给「很帅的年糕」发一条真实私信（唯一没验过的链路）。
2. **朋友圈三选一**：A 重启客户端后机器人发（顺带解锁配图排查）/ B 手机手动发（物料在 outbox/）/ C 先搁着。
3. **小红点方案**：维持现状 or 换“徽标优先”观察。

---

*本 README 由 2026-10-17 重写整理；v1 历史版本（含全部轮次记录）存档于 docs/archive/README-v1-20261017.md。*