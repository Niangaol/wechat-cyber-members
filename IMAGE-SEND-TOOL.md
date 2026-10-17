# 独立发图工具（不接入常驻 Agent）

本工具仅把**人工明确指定的本地图片**提交到已登记的微信会话。
不会停止/重启 Agent，不改运行配置、不改自动回复提示词；不调用生图或聊天模型，不允许群消息自动触发。
新增入口：
-  wsl/send-image.py（命令行）
-  src/image_send_tool.py（实现）

## 1. 先预检（不操作 UI、剪贴板，不写运行时账本）

在 Windows Git Bash 直接执行以下命令，以现成 OC 图与测试群为例：

```bash
wsl.exe -d Ubuntu-24.04 -u niangao -e python3 /mnt/d/AgentPrograms/wechat-bot/wsl/send-image.py \
  --chat "Agent 聊天测试群" \
  --image /mnt/d/AgentPrograms/wechat-bot/config/assets/oc-reference.png
```

返回 JSON：status=PREFLIGHT、chat、sha256、bytes、width、height、ui_touched=false。
这是**本地文件与配置授权预检**，不代表微信当前登录、标题可读、输入框为空或能送达。
图片最长边会缩至 2048，转换为白底 PNG 并丢弃元数据；原文件不变。
PNG/JPEG/WebP 静态图有效，输入和输出均限 20MB、输入限1600万像素；动画/远程URL不支持。

## 2. 明确执行（会真实发送，勿当测试随便运行）

先确认你愿意把上图发给该群，再把以下命令中的 SHA256 替换成**上一步返回的完整 sha256**：

```bash
wsl.exe -d Ubuntu-24.04 -u niangao -e python3 /mnt/d/AgentPrograms/wechat-bot/wsl/send-image.py \
  --chat "Agent 聊天测试群" \
  --image /mnt/d/AgentPrograms/wechat-bot/config/assets/oc-reference.png \
  --execute \
  --confirm-chat "Agent 聊天测试群" \
  --sha256 "替换成预检返回的完整SHA256" \
  --request-id oc-test-001
```

预检后图片变更、确认目标或摘要不一致都会阻断。request-id 仅支持字母、数字、下划线和短横线。
目前不提供附带文字、不自动生图、不发送其他文件或表情包。
工具需要当前 WSL 剪贴板可备份为 PNG 或文本；未知格式/无可读选择区时保守拒绝。
执行期间尽量不要操作微信与剪贴板。

## 安全与并行边界

- 与 Agent 共用现有 wechat-ui.lock。锁忙则立即返回 BUSY（退出码3），不抢窗口、不写尝试记录，可稍后人工重跑。
- Agent 进程继续运行。但二者使用同一微信 UI，工具取得锁时 Agent 会跳过该轮 UI 工作；这不是零延迟或UI并发发送。
- 目标必须与配置登记名称原样一致。群受 group_whitelist 约束；私聊限 target_chat/direct_whitelist，尊重 direct_enabled 和 direct_blacklist。
- 每个关键阶段核对标题、STOP、授权；标题不符/未登录/不支持的窗口布局不发送。
- 支持现有1021×740布局；预览检查只看输入区的新增变化，不拿聊天区已有图片当作预览。检测是保守像素检查，不是内容语义识别，特殊纯色/低对比图可能被拒绝。
- 原有文字或图片草稿不覆盖。遇到不确定情况，不自动清草稿、不再次按发送键。失败可能保留本工具的图片预览，需人工核查；该会话自动回复也可能被草稿安全闸暂时拦住。
- 尝试在操作UI前写入独立 image-tool/attempts.sqlite，不改 Agent 的 ledger.sqlite；按 Return 前先记 SUBMITTING。
- 同 request-id 或同会话+同规范化图片内容再次执行，都会 DUPLICATE_BLOCKED（退出码4）。STARTED/SUBMITTING/UNCERTAIN 也阻止重试；不能靠换id绕过。当前不提供强制重发/自动清账命令。
- 剪贴板会备份一种支持的格式并在持锁期间恢复；不保证还原富文本等其他格式。恢复失败时结果按不确定处理。
- SUBMITTED 只代表已按发送、输入区本地检查清空；delivery_confirmed=false，**不是服务器/收件人送达回执**。请在微信里人工核对。
- BLOCKED_OR_UNCERTAIN（退出码2）不自动重试；可能已产生UI或发送副作用，必须先人工检查。
- 文件内容由操作者负责，本工具不做图片内容审核；它没有开放给微信模型调用。

## 当前验收边界

已做离线单测和真实文件的只读预检；尚未在本轮实际发图，不把旧的“粘贴到预览”验收当成发送成功。
若要补实机验收，请明确指定**图片与接收会话**。不要运行旧调试脚本来验收（可能没锁、默认目标或错误预览坐标）。

## 2026-10-17 实机验收（已真实发出）

- 目标：Agent 聊天测试群；图片：`~/.local/state/wechat-bot/media/gen-1792214474.png`（千问生图，2048×2048，sha256 04852677…f6da30）。
- 结果：`status=SUBMITTED`（request-id `oc-test-003`），截屏核验群聊里确实出现了图片气泡，输入区清空。
- 修正了三处"预览但发不出"的问题（都已回归测试）：
  1. 输入区区域：`COMPOSER=(300,632,890,680)` 会把左侧会话列表/笑脸图标/文本光标算成"已有内容" → 改成 `(345,632,890,680)`，并把空白阈值从 64 改成 300（空输入框实测 40–70 px 光标，图片预览实测 5337 px）。
  2. 预览稳定性：用逐字节比较会被闪烁的绿色光标破坏（两次截图必然不同）→ 改成 `composer_stable()`（差异像素 ≤260 才算没变）。
  3. 空剪贴板：没有进程持有剪贴板时 `xclip -out` 返回 rc=1，原来会拒绝发送 → 现在按 `('none', b'')` 处理，不备份也不恢复。
- 两次发送前中止的尝试（oc-test-001/002，均卡在安全检查、**从未按过 Return**）已在 attempts.sqlite 里审计标记为 `ABORTED_PRE_SEND`，再发用新 request-id。

## 回复链路发图（机器人自己发）

`config/resident.json` 的 `image_reply`：用户消息里出现"发图/发张图/画一张/生成图片…"→ 文字回复发出后，用 OC 参考图生图并通过同一套已验证链路发送；每会话每小时最多 3 张；失败只记录，不影响文字回复。`enabled=false` 可整体关闭。

### 2026-10-17 14:12 回复链路实机验收（已真实发出）

- 用真实 Resident + 真实配置 + 真实生图调用 `maybe_send_image_reply("发个图看看你长什么样")` → `ok=True`（总耗时 29s，其中生图约 25s），截屏确认测试群里出现 OC 年糕图、输入区清空。
- 这次还修掉一个**静默失败**：不先 `xdotool windowfocus` 激活窗口就直接点输入区，粘贴会**什么都不发生**（Weston 下点击不会自动聚焦窗口，输入框拿不到键盘焦点）。表现是"预览没出现、未按发送键"，但剪贴板内容是对的。现在 `send_text` / `send_image_png` / 独立工具都会先 `focus_window()`。
- 这也是之前"发图偶尔失败但看不出原因"的一个根因：只要窗口不在前台，粘贴就静默失败。
