# QQ 接入（NapCat + NoneBot2）独立对抗式验证报告

验证者：**qq-verifier**（独立于实现者）。全中文。
只读 `qq/**`、`src/**`、`wsl/**`、`config/**`；未执行任何 git 命令（无 checkout/reset）；
不连真实 QQ/NapCat/微信，不出网；不读写生产状态目录。所有写入只发生在 `verify_qq/` 与 tmpdir。

---

## 0. 被验证快照（结论只对这组指纹负责）

```
410860f9…  qq/core/__init__.py        56fb7b80…  qq/core/envelope.py
76430258…  qq/core/bridge.py          0a907add…  qq/core/media.py
b3f4ebb1…  qq/core/config.py          e49790c6…  qq/core/policy.py
9407ca19…  qq/core/service.py         f099adc5…  qq/core/store.py
c67b39e8…  qq/core/worker.py          c0e57c8b…  qq/bot.py
cf9892f0…  qq/plugins/__init__.py     24602b3f…  qq/plugins/qq_chat.py
e6defd07…  test_qq_core.py            19e32f5d…  test_qq_core_policy.py
7735d2be…  test_qq_plugin.py          b080ebfd…  test_qq_deploy.py
6c4874cf…  test_qq_shared_state.py
```

## 1. 复现方式

```bash
# 全部验证（约 3 分钟，不含突变测试）
MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu-24.04 -- bash -lc \
  'cd /mnt/d/AgentPrograms/wechat-bot && bash verify_qq/final_pass.sh'

# 突变测试（约 8 分钟，25 个突变）
MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu-24.04 -- bash -lc \
  'cd /mnt/d/AgentPrograms/wechat-bot && python3 verify_qq/v6_mutation.py'
```

---

## 2. 结论总表

| # | 验证项 | 结论 | 自建用例 |
|---|--------|------|---------|
| 1 | envelope.from_onebot_event（string CQ / array / @全体 vs @我 / 自己发的 / message_id 缺失 / notice·request·meta / 私聊·群聊 chat_key 与 dedupe_key） | **PASS** | v1：117 项全过 |
| 2 | policy.decide（未登记群 / 私聊黑白名单 / 真 @ vs 文本假装 @ / followup / plain_mode 四档 / plain_per_hour / plain_cooldown_s / min_reply_seconds / 类型写错不 fail-open） | **PASS** | v2：129 项全过 |
| 3 | media.fetch_image（私网·本机·混合 DNS / 跳转进私网 / 超大小 / 假魔数 / 像素炸弹 / 非 80·443 端口 / 失败返回 None） | **PASS** | v3：109 项全过 |
| 4 | worker/service（同 message_id 只处理一次 / STOP / auto_send / unknown 不重发 / 超长拦下 / WAITING_QUOTA / 队列满 / 过期 / 每小时上限 / 生图失败不影响文字 / 跨 self_id·跨平台隔离） | **PASS**（附 1 处缺陷 D1） | v4：137 项全过 |
| 5 | 线程与集成（跨线程 submit / status.json 原子写与心跳 / qq/core 不 import nonebot / bot.py token fail-closed） | **PASS** | v5：113 项全过 |
| 6 | 推翻现有测试（突变测试 + 弱断言扫描） | **部分 PASS**：25 个突变杀死 22、存活 3（2 个是真缺口，1 个是等价突变） | v6 / v7 / v8 |

现有测试基线（仓库自带 5 个套件）：**Ran 283 tests … OK (skipped=7)**。

---

## 3. 缺陷清单（按严重度排序，含最小复现）

### D1（中）`last_send_ok_at` 会被"结果未知"的发送刷新

- 位置：`qq/core/worker.py` unknown 分支与 ok 分支都调用
  `note_reply_sent(chat_key, priority)`（默认 `confirmed=True`）；
  `qq/core/service.py` 的 `note_reply_sent(..., confirmed=True)` 专门为 unknown 设计了
  `confirmed=False` 这条路——**从未被调用，是死代码**。
- 影响：契约 §7 的 status 字段 `last_send_ok_at` 语义是"最近一次**确认**发出"。
  发送超时（unknown）时它照样被刷新，看门狗/运维会以为消息已确认送达；
  而同一条消息在 `send_log` 里 state=`unknown`，两处自相矛盾。
- 最小复现：`python3 verify_qq/v4_service.py`（探针 `t_last_send_ok_at_semantics`）——
  FakeSender 返回 `SendResult(ok=False, unknown=True, error='超时')`。
  真实输出：
  ```
  [OBSERVE] （缺陷·中）unknown（结果未知）的发送把 last_send_ok_at 刷新了
            <- last_send_ok_at=1792318485.95，台账 state=unknown
  [PASS] confirmed=False 确实不刷 last_send_ok_at（参数有效但调用点没用）  <- got=0.0
  ```
- 建议：unknown 分支改传 `confirmed=False`。

### D2（中·测试缺口）STOP 在位时"不生成、不花额度"没有任何测试覆盖

- 把 `worker._process` 里生成前那道 STOP 检查删掉，25 个突变里**它存活**（测试全绿）。
  发送前还有第二道 STOP，所以"不发送"这个结果没变——但**每条消息仍会白调一次模型、白花一次额度**。
- 现有覆盖：`StopFileTests` 只有
  `test_stop_file_blocks_speaking_until_removed`、`test_stop_checked_again_right_before_sending`，
  两个都只断言"不发送"。
- 最小复现：`python3 verify_qq/v8_survivor_probe.py`，真实输出：
  ```
  [PASS] STOP 在位：不发送            <- got=[] want=[]
  [PASS] STOP 在位：不调模型（生成前那道检查负责）  <- got=0 want=0
  [PASS] STOP 在位：不花额度          <- got=0 want=0
  StopFileTests 里的用例：['test_stop_file_blocks_speaking_until_removed',
                          'test_stop_checked_again_right_before_sending']
  其中是否断言了"没有调模型"：False
  ```
- 建议：补一条 `assertEqual(model.call_count, 0)` 与 `quota.status()['used_5h'] == 0`。

### D3（中·测试缺口）"群条目合法但不写 plain_mode"这条最保守默认值没有覆盖

- 把 `policy.DEFAULT_PLAIN_MODE` 从 `'at_only'` 改成 `'all'`，测试**仍全绿**（M07 存活）。
- 影响：`groups` 里只写群号（运维最常见的写法）时，默认值一旦回归成 `all`，
  所有已登记群会对**全部闲聊**回话——费用与骚扰风险，且 CI 不会响。
- 现有测试里的 `groups` 写法只有两类：坏类型（`{'123': 'idle'}`）或显式写了 plain_mode，
  没有"合法 dict 条目 + 不写 plain_mode"的用例。
- 最小复现：`python3 verify_qq/v8_survivor_probe.py`（第一组），真实输出：
  ```
  当前 DEFAULT_PLAIN_MODE <- got='at_only' want='at_only'
  groups 里只写群号（没写 plain_mode）时的判定：context_only/2/plain_at_only
  [OBSERVE]（测试缺口·中）… 20 个突变里只有这一个存活
  ```

### D4（低-中）`config.normalize` 的告警文案与 policy 实际行为相反，且方向更宽松

- `groups["30003"].plain_mode = "ALL"`：normalize 原样保留并告警"不是
  at_only/selective/idle/all 之一，**按最保守的 at_only 处理**"；
  但 policy 里 `_text(...).strip().lower()` 会把它变成 `all`，**实际回所有闲聊**。
- 最小复现：`python3 verify_qq/v2_policy.py | grep -A3 normalize`，真实输出：
  ```
  normalize 原样保留的 plain_mode = 'ALL'
  normalize 的告警 = ["groups[30003].plain_mode='ALL' 不是 at_only/selective/idle/all 之一，按最保守的 at_only 处理"]
  policy 实际判定 = reply/2/plain_all
  ```
- 建议：normalize 里一并 `.lower()` 后再校验（认可大写），或 policy 不再 lower()。

### D5（低）交付的测试套件里有一个 flaky 用例（实测 20% 概率红）

- `test_qq_core.StatusTests.test_status_has_contract_fields_and_is_written_atomically`
  断言状态目录里不留 `.status.json.*.tmp`；但心跳线程 `_status_loop` 每 0.5s 也在原子写
  status.json，`write_text` 与 `replace` 之间存在窗口。
- 真实输出（单跑 25 次）：
  ```
  单跑 25 次：PASS=20 FAIL=5
  AssertionError: Lists differ:
    [PosixPath('/tmp/qq-core-kpi1f9rs/.status.json.2.tmp')] != []
  ```
- 注意：这是**测试写法**的竞态，不是 `atomic_json` 的缺陷（rename 本身是原子的），
  也不是产品缺陷；但会让 CI 随机变红、也会掩盖真失败。
- 建议：断言前先 `service.stop()`，或忽略"当前正在写的那个 tmp"。
- 副作用提示：我第一次跑突变测试时基线就是被它判红的（脚本已改为按"新增失败用例集合"判定，
  并剔除这个已知 flaky 用例，见 `v6_mutation.py` 的 `FLAKY` 常量）。

### D6（低）组播地址能通过 `public_endpoint`（media 继承了 src/web_reader.py 的行为）

- Python 3.12 里 `ipaddress.ip_address('224.0.0.1').is_global` 是 **True**，
  所以 `public_endpoint('http://224.0.0.1/x.png')` 放行。契约 §5 的字面要求
  （"所有地址必须 is_global"）被满足，但语义上漏了 224.0.0.0/4。
- 实际可利用性低：TCP 连组播通常直接 ENETUNREACH → `fetch_image` 最终仍是 None。
  但这是 SSRF 面上不该有的一处放行，且 `src/web_reader.py` 被微信侧 `fetch_public_text` 共用。
- 真实输出（`python3 verify_qq/_probe_webreader.py`）：
  ```
  224.0.0.1  is_global=True  is_private=False is_multicast=True
  http://224.0.0.1/x.png   通过 -> '224.0.0.1'
  http://240.0.0.1/x.png   拒绝 WebSafetyError: 禁止私网、本机、保留地址和混合DNS结果
  ```

### D7（低）`http://host:0/` 的端口 0 被 `p.port or 80` 折成 80

- 不是绕过（80 本就在白名单里），但"端口 0"没有走到"禁止非标准端口"。
  同为 `src/web_reader.py` 的既有写法。

### D8（低）`_as_id(0)` 得到字符串 `'0'`（真值），`self_id=0`/`message_id=0` 不会被丢弃

- 契约 §2 要求"拿不到 message_id → 丢弃（否则无法去重）"。0 明显不是合法 id 却当有效值。
  若某客户端对多条消息都给 `message_id=0`，它们会共用同一个 dedupe_key 而互相顶掉。
- 现实里 NapCat 不会给 0，属健壮性缺口（v1 里记为 OBSERVE）。

### D9（低）非标准大写 CQ 码 `[CQ:AT,QQ=10001]` 识别不出 `at_me`

- `parse_cq_string` 把段类型小写化（`AT`→`at`），但**没有把参数键 `QQ` 小写化** →
  `data.get('qq')` 取不到。OneBot 规范是小写，属健壮性缺口。

### D10（低）§7.1 的两条能力已实现，但 `docs/QQ.md` 与 `qq.example.json` 里都没有 `links` 一节

- 功能上没问题：`config.normalize` 会给 `links` 补默认值（实测
  `{'enabled': True, 'max_urls': 2, 'max_bytes': 250000, 'max_chars': 9000, 'timeout': 10, 'total_budget_seconds': 12}`），
  所以**默认是开的**，链接阅读真的会跑（v4 里 10 项验证全 PASS）。
- 但运维在示例配置和 `docs/QQ.md`（全文 0 处提到 links/链接）里看不到这个键，
  既不知道它会出网读链接，也无从调上限。
- 另请 lead 明确取舍：`links.enabled` 默认 **True**（用户贴的任意 URL 都会触发一次出网抓取，
  受 web_reader 公网限制），而 `hot_feed` 是**刻意默认关**的。两者默认不一致。

### D11（低·产品取舍）`@全体` 在 at_only 群里不会应声

- 契约 §2 明确 at_all 不算 at_me，§3 只对 at_me 规定 reply → 实现**符合契约**。
  但这意味着"群主 @全体 通知"机器人不理。契约没写，建议 lead 确认是否有意为之。

### D12（信息）被验证对象在验证期间持续改动

- 18:05–18:11 期间 `qq/core/service.py` 从 753 行涨到 846 行、`worker.py` 393→488、
  `config.py` 336→341；基线测试数 265 → 282 → 283。
- **18:10:59 那一版 service.py 是语法错误的**（`URL_TRAILING = '.,;:!?'"…"'` 未闭合字符串），
  我的探针撞上了一次 SyntaxError；几秒后作者就修好了。
- 我最初 grep 到"§7.1 的两条能力没实现"是**过期快照**造成的误判，已在新快照上推翻：
  `gather_sources` / `extract_urls` / `learn_cycle` 都在，v4 里相关 10 项全 PASS。
- 教训：本报告 qq/** 的结论只对第 0 节的 sha256 负责；之后若再改动需重跑 `verify_qq/final_pass.sh`。

---

## 4. 存疑项（需 lead 裁决，不算缺陷）

- **S1**：契约 §3 开头写"配置缺失/类型不对 → ignore"，但 §3 的判定顺序把 `at_me` 放在第①步。
  实测：`groups[g]` 的 `plain_mode` / `followup_window_s` / `plain_cooldown_s` /
  `plain_per_hour` / `mention_aliases` 类型写错时（6 例），**真 @ 仍然会 reply**。
  我倾向认为这符合 §3 判定顺序（@ 路径根本不读这些字段），不是 fail-open；
  但两种读法结论相反，请把结论写进契约。
- **S2**：`_pick` 的"群 → 全局回退"只覆盖
  `followup_window_s`/`plain_cooldown_s`/`plain_per_hour`/`mention_aliases`，
  `plain_mode` **不回退**（顶层写 `plain_mode` 无效，回退成 at_only）。
  方向更保守、无安全影响，但与模块内注释"两处都支持，读法只有一种"不一致。
- **S3**：`[CQ:reply]`（引用回复机器人）不算"被 @"，at_only 群里引用回复机器人不会触发回话。
  契约没写，属产品取舍。

---

## 5. 突变测试完整结果（25 个突变，杀死 22，存活 3）

```
M01 @全体 被当成 @我                 杀死  M14 seen() 永不去重              杀死
M02 不再丢弃"自己发的消息"             杀死  M15 auto_send=false 也照样发送    杀死
M03 message_id 缺失也放行             杀死  M16 STOP 不再拦住发送             *** 存活 ***
M04 dedupe_key 去掉 self_id           杀死  M17 跳过输出安全闸               杀死
M05 未登记的群也回话                  杀死  M18 unknown 记成 ok 台账          杀死
M06 配置类型不对时 fail-OPEN          杀死  M19 queue_full 闸失效             杀死
M07 plain_mode 默认改成 all           *** 存活 ***  M20 跳过任务保鲜期      杀死
M08 别名命中降级成普通优先级           杀死  M21 普通回复全变成 context_only   杀死
M09 去掉 min_reply_seconds 频率闸     杀死  M22 真 @ 优先级降级              杀死
M10 私聊黑名单失效                    杀死  M23 追问命中降级                杀死
M11 去掉像素上限（解压炸弹）           杀死  M24 plain_per_hour 上限失效      杀死
M12 去掉端口白名单                    *** 存活 ***  M25 idle 队列忙判定失效   杀死
M13 失败时把异常抛给调用方             杀死
```

**存活项定性**（`v8_survivor_probe.py` 逐个核查）：

| 突变 | 定性 | 依据 |
|------|------|------|
| M07 | **真测试缺口（中）** → D3 | 25 个突变里唯一因"默认值"存活的；没有用例覆盖"合法群条目不写 plain_mode" |
| M12 | **等价突变，不算缺口** | 默认 resolver（`public_endpoint`）自己就拒绝非 80/443（实测 3/3），`_fetch` 那道是纵深防御；生产路径 `QQService.fetch_image` 不注入 resolver，所以删掉后行为不可观测 |
| M16 | **真测试缺口（中）** → D2 | 发送前的第二道 STOP 兜住了结果，但"不生成/不花额度"无人断言 |

另外说明：M12 存活**不代表**"端口限制没被测"——`test_qq_core.MediaTests` 与我的 v3 都有端口用例，
它们走的是真实 resolver，一样会红。

---

## 6. 弱断言静态扫描（v7）

对 5 个测试文件做 AST 扫描：**283 个测试方法、741 条断言**。

- A 类"只断言 reason、不断言 action"：命中 4 处 →
  **人工复核后全部证伪**：这 4 个用例都额外用 `sender.texts`（发没发出去）间接验证了 action，
  例如 `test_all_group_replies` 同时断言 `len(sender.texts) == 1`。**没有发现 reason-only 盲区**。
- B 类"只断言 action、不断言 priority"：命中 42 处 → 用突变 M22/M23/M08 实测反证：
  把 @、别名、追问的优先级降级，**全部被杀死**（例：`test_at_me_replies_with_top_priority`）。
  所以优先级维度实际是被覆盖的。
- C 类"没有任何断言"：0 处。D 类"恒真表达式"：0 处。

结论：**现有测试的断言强度总体是够的**（22/25 突变被杀死），
发现的两个真缺口都是"某个具体场景没被想到"，而不是"断言写虚了"。

---

## 7. 我有没有改过任何非 verify_qq/ 的文件（如实回答）

**没有。** 具体说明：

- 所有 `write`/`edit` 只落在 `verify_qq/**`；突变测试的"注入错误"全部发生在
  `verify_qq/mutations/<编号>/` 的**副本**里，`src/` 在副本中是只读符号链接。
- **未执行任何 git 命令**（没有 checkout / reset / stash / clean / status / diff）。
- 未连接真实 QQ/NapCat/微信、未出网。media 的唯一"负例"是 127.0.0.1 上的本地 HTTP 服务器，
  且该服务器**一个请求都没收到**（证明连接在校验阶段就被拦下）：
  `[PASS] 被拒绝的本机请求一次都没打到服务器上 <- got=[] want=[]`。
- 未读写生产状态目录：v5 里显式断言 `~/.local/state/qq-bot` 的内容集合在验证前后完全一致
  （`got == want == {'qq.db','qq.db-wal','qq.db-shm','status.json','media'}`）；
  所有测试状态都建在 `/tmp/verify-qq-*` 的 tmpdir 里。
- **一处需要如实说明的副作用**：跑测试与 `py_compile` 会刷新 Python 字节码缓存
  （`qq/core/__pycache__/*.pyc`、`src/__pycache__/*.pyc`、`__pycache__/test_qq_*.pyc`、
  `wsl/__pycache__/qq-health.cpython-312.pyc`、`qq-acceptance.cpython-312.pyc`）。
  这些都是可自动重建的缓存，**不是源文件**，我没有增删任何源文件。
  证据：`qq/core/*.py` 的 sha256 在 18:12 与 18:32 两次核对**完全一致**（见第 0 节）。
- 仓库在验证期间还有别的写入者，**都不是我**：`src/resident.py`、`test_link_url_extract.py`、
  `logs/watchdog*`、`.gitignore`、`qq/core/INTERFACES.md`(18:03)、
  `qq/core/{config,service,worker}.py`(18:05–18:11)。

---

## 8. verify_qq/ 目录内容

| 文件 | 说明 |
|------|------|
| `_env.py` | 环境自检 |
| `harness.py` | 极简断言框架（PASS/FAIL/OBSERVE + 汇总 + 退出码） |
| `v1_envelope.py` | §2 事件解析，117 项 |
| `v2_policy.py` | §3 接话判定与 fail-closed 矩阵，129 项 |
| `v3_media.py` | §5 图片下载安全边界，109 项 |
| `v4_service.py` | §4/§6/§7 状态机、线程、隔离、§7.1，137 项 |
| `v5_integration.py` | §1/§8/§9 纯净性、token、发送目标、部署，113 项 |
| `v6_mutation.py` | 突变测试（25 个突变） |
| `v7_weak_tests.py` | 弱断言 AST 扫描 |
| `v8_survivor_probe.py` | 存活突变的逐个定性 |
| `v9_flaky.sh` | flaky 用例量化 |
| `_probe_webreader.py` / `_probe_ctx.py` / `_probe_skips.py` | 单点探针 |
| `final_pass.sh` / `run_all.sh` | 一键复现 |
| `mutation-report.txt` / `mutation-report-extra.txt` | 突变测试原始输出 |
| `mutations/` | 突变副本（可整目录删除，不影响仓库） |
| `_isolate.py` / `_v4_*.sh` / `_probe_stop*.py` / `_diff_snapshots.sh` | 第二轮排查用脚本（隔离探针 / 复现 flaky / 用副本当历史快照） |

---

# 第二轮：契约 §10 更新后的重新验证（2026-10-18 19:1x）

lead 反馈：契约已更新（`qq/core/INTERFACES.md` §10，sha256 `497e1c2f…`），我的 6 条 FAIL 里 5 条是
断言过期，并逐条给了裁决。以下是按新契约更新断言后的复验结果。

## A. 被验证快照（第二轮）

```
410860f9…  qq/core/__init__.py      befbb391…  qq/core/config.py
76430258…  qq/core/bridge.py        f5fc02ff…  qq/core/envelope.py
0a907add…  qq/core/media.py         fae02c3c…  qq/core/policy.py
9407ca19…  qq/core/service.py       f099adc5…  qq/core/store.py
e291d82c…  qq/core/worker.py        c0e57c8b…  qq/bot.py
cf9892f0…  qq/plugins/__init__.py   24602b3f…  qq/plugins/qq_chat.py
fa214f36…  test_qq_core.py          4dfb2ef2…  test_qq_core_policy.py
6aa70308…  test_qq_plugin.py        b080ebfd…  test_qq_deploy.py
6c4874cf…  test_qq_shared_state.py
```

仓库自带基线：**Ran 300 tests … OK (skipped=7)**。

## B. 结论表（第二轮）

| 套件 | 项数 | 结论 |
|------|------|------|
| v1_envelope | 137 | **PASS 137 / FAIL 0** |
| v2_policy | 179 | **PASS 179 / FAIL 0** |
| v3_media | 127 | **PASS 127 / FAIL 0** |
| v4_service | 141 | **PASS 141 / FAIL 0** |
| v5_integration | 113 | **PASS 113 / FAIL 0** |
| v8 存活突变核查 | 12 | **PASS 12 / FAIL 0** |
| v6 突变测试 | 25 个突变 | **杀死 24 / 存活 1（M12，已证等价）** |

## C. 三条过期断言怎么改的

### C1 大写 CQ 参数键（§10）
- 旧断言："参数键原样保留（未小写化）`['QQ']`"、"大写 `[CQ:AT,QQ=…]` 识别不出 at_me"（OBSERVE）。
- 新断言：参数键统一小写 `['qq']`；`[CQ:AT,QQ=<self>]` **必须** `at_me=True`。
  另加 4 种大小写组合（全大写 / 混合 / 类型小写键大写 / 类型大写键混合）、
  大写 `[CQ:AT,QQ=all]` 只算 at_all、大写 `[CQ:IMAGE,File=…,URL=…]` 也要能取 url 且 text 干净。
- 边界（保留为 OBSERVE）：小写 `[cq:at,...]` 整体不当 CQ 码解析 —— §10 只要求"参数键"小写化，
  OneBot 规范里 CQ 前缀就是大写，实现保留现状合理。

### C2 fail-closed 4（实为 5）条（§10 S1）
按裁决把配置类型错误分成两类，**作用域也分开**（拿错事件类型会把"字段本来就不管这个会话"误判成 fail-open）：

- **A 类 身份/名单字段 → 必须 ignore**（10 例）：
  `direct_policy`（数字/不认识的值/list）、`direct_blacklist`（字符串）、
  `direct_whitelist`（数字）、`min_reply_seconds`（字符串/bool）、
  `groups` 不是 dict、`groups[g]` 不是 dict。
  其中 `min_reply_seconds` 是 §3.4 的**全局**闸 → 私聊、群 @ 都必须 ignore；
  `direct_*` 只管私聊 → 只用私聊事件断言，并**反向断言"它不该拦群 @"**（防过度拦截）。
- **B 类 策略字段 → 按字段缺失用默认值**（11 例）：`plain_mode`（数字/list/不认识的字符串）、
  `followup_window_s`（字符串/bool）、`plain_cooldown_s`（bool/字符串）、
  `plain_per_hour`（字符串/bool）、`mention_aliases`（字符串/数字）。
  每条都断言两件事：① **不 fail-open**（该保守时仍保守，普通消息绝不因此变 reply）；
  ② **不影响真 @**（照常 reply/at_me）。

两个我自己踩到的坑，记下来免得下次再犯：
1. 第一版我拿**群事件**去测 `direct_policy`（私聊专属字段），误判成 fail-open —— 已按作用域拆开。
2. 第二版我把"群普通消息"也要求 ignore；实际 at_only 群里它本来就是 context_only，
   频率闸根本不会被读到 —— 改成断言"**绝不 reply**"（这才是安全属性）。

### C3 M07 / M12 / M16 三个存活突变
- **M07（同源，已闭合）**：突改的位置**就是** `DEFAULT_PLAIN_MODE` 常量本身，
  而它就是"群条目没写 plain_mode"这条默认值的唯一来源；新实现里 `_safe_mode` 的兜底
  也返回它，所以三种路径（不写 / 写错类型 / 兜底）**同源**。
  qq-core 已补两条腿：`assertEqual(policy.DEFAULT_PLAIN_MODE,'at_only')`（钉常量）
  + `test_group_without_plain_mode_stays_conservative_end_to_end`（钉行为）。
  第二轮突变 **M07 被杀死（4 个用例变红）**。
- **M12（等价突变，保留说明）**：存活但**不代表缺口**。默认 resolver `public_endpoint`
  自己就拒绝非 80/443（v8 实测 3/3），§10 D7 之后还额外拒了端口 0；
  生产路径 `QQService.fetch_image` 不注入 resolver，所以 `_fetch` 里那道删掉后行为不可观测 —— 纵深防御。
- **M16（已闭合）**：`StopFileTests` 现在有三条用例，新增的
  `test_stop_check_inside_processing_blocks_generation` 同时断言"不调模型"与"不花额度"。
  第二轮突变 **M16 被杀死**。

## D. 顺带确认：§10 里我已经报过的 D6/D7 确实修了

| 项 | 修前 | 修后（实测） |
|----|------|-------------|
| D6 组播 | `http://224.0.0.1/x.png` 通过 | 拒绝；`239.255.255.250`、`233.1.2.3`、`[ff02::1]`、`[ff00::1]` 全拒 |
| D7 端口 0 | `p.port or 80` 折成 80 | `禁止端口 0` |
| 对照 | — | 真公网 `93.184.216.34` 仍放行（证明不是"全拒"假阳性） |

v3 里这两项已从 OBSERVE 升级为**严格断言**（含"前提断言"：确认 224.0.0.1 的 `is_global` 确实是 True，
所以只看它会漏 —— 防止将来有人以为这条检查多余而删掉）。

## E. 第一轮报的 D1（last_send_ok_at 被 unknown 刷新）也已修复

`worker.py` 的 unknown 分支现在传 `note_reply_sent(..., confirmed=False)`；
仓库新增 `test_unknown_send_does_not_refresh_confirmed_timestamp`（M18 被杀死）。
我把 v4 里原先那条 OBSERVE 改成了**双向严格断言**：
unknown 不刷 `last_send_ok_at` 但仍记"刚说过话"；ok 必须刷；`confirmed=False` 参数仍有效。

## F. 存疑项：一次未能复现的间歇性失败（如实记录，**不断言为实现缺陷**）

复验过程中，`v4_service.py` 出现过 **2 次**失败，形态都是"**本该不发送，却发送了**"：
- 第 1 次：`t_stop_during_generation`（断言 `生成后写 STOP → 不发送`、`任务状态记成 STOPPED`）
  实际 got `[('qq:10001:group:30003','生成好了但已被叫停')]` / state `SENT`；
- 第 2 次：`t_context_only_still_recorded`（`context_only 不发送` / `不调模型` / `状态记成 CONTEXT_ONLY`）
  实际 got 发出 `'好的'`、`call_count=1`、state `SENT`。

我做了什么排查（都没能复现，也没能把锅钉死）：
- 两个探针**隔离单跑 5 次**全绿；
- 全套 v4 **连跑 12 次**全绿；
- 带 `decide` 探针的调试副本 **连跑 8 次**全绿；
- **4 进程并发**（制造 CPU 竞争）跑 4 轮 = **16 次**全绿；
- 两个探针都是纯单线程、输入全确定（`at_me=False`、`last_reply_at=0`、
  `group_plain_times=[]`、`plain_mode='at_only'`），按代码推演**不可能**得到 reply。

关键证据：我用自己的突变副本当历史快照比对，**`qq/core` 的内容哈希在失败前后完全一致**
（`policy.py` 在 19:04、`worker.py` 在 19:02 被重写过，但内容与我 18:59 记录的一致），
所以**不能**用"代码在我眼皮底下变了"解释。

我的判断：**证据不足以断言实现有缺陷**，最可能是我的用例在高负载下的抖动
（或那两次运行恰好撞上源文件被并发重写的瞬间 —— `worker.py` mtime 19:02:54 正落在失败窗口里，
而 `Path.write_text` 不是原子写，读者可能读到撕裂的文件）。
**方向是"多发"（不是漏发），所以我把这条报上来请你和 qq-core 留意**：
如果后续在负载下再看到同类"该不发却发了"，值得优先查 `_process` 里 STOP 与 action 的读取时序。

### F.1 lead 假设"跨用例串扰"的自查结论：**已证伪**

lead 的假设是最可能的解释是"probe 跨用例共用 state_dir/qq.db + 同一个 QQService，
于是某个用例领到了前一个用例遗留的 PENDING/WAITING_QUOTA 任务并发送"。我做了三层自查：

**1）静态：每个用例独立 state_dir / qq.db / QQService**
`build()` 默认走 `tempfile.mkdtemp(dir=TMPROOT)`，每次都是**全新目录**，
`db_path = <新目录>/qq.db`，并 `QQService(...)` 新建实例。
实测：47 次 `build()` → **46 个不同 state_dir**；唯一重复的那个是
`t_dedupe_survives_restart`（**显式**复用同一个 tmp，就是为了测"重启后仍去重"）。

**2）运行时：钩住 `Quota.enqueue` 与 `Worker.process` 做配对审计**
（脚本 `verify_qq/_isolation_audit.py`，一次进程跑完全部探针）
```
服务实例数：47        不同 db_path 数：46
enqueue 次数：166；process 次数：83
A. db_path 重复的：只有 t_dedupe_survives_restart(explicit) —— 设计如此
B. 被 process 的任务都能在**同一个库**上找到 enqueue：是
C. 未配对的 process 记录：无
D. "处理次数 > 入队次数"的库：t_quota_exhausted_waits (2,1)
E. 同一个 (库, qid) 被 process() 两次：t_quota_exhausted_waits
结论：未发现任何跨用例串扰
```
D/E 那一条是 **WAITING_QUOTA 的设计**：第一次 `process()` 只把任务 park 成
`WAITING_QUOTA`（不发送、不调模型），额度恢复后第二次才真处理 —— 该探针自己断言了
**恰好发送 1 条**，所以不是重复发送。
（自查过程中我先写了一版用 `id(conn)` 当库标识的审计，结果报了一堆假阳性：
Python 回收对象后会**复用地址**，不同用例的连接撞到同一个 id。已改成用 db 路径做键。）

**3）加硬护栏 + 连跑 20 次**
`build()` 里新增断言：新用例拿到的服务，`depth() + waiting_count()` 必须为 0，
否则当场 `raise`；并禁止自动生成的 state_dir 被两个用例共用。
另外给两个可疑探针补了"收尾后无待办残留""队列里只有这一条任务"的断言。
```
用例隔离审计：build() 47 次，不同 state_dir 46 个，新用例拿到"非空队列"的次数：0
连跑 20 次：PASS=20 FAIL=0
```
（加上此前的 41 次 + 4 进程并发 16 次，失败之后累计 **77 次连跑全绿**。）

**结论**：串扰解释**不成立** —— 每个用例都是全新的 state_dir/qq.db/QQService，
且没有任何任务被"不是它入队的那个库"处理过。

### F.2 异常结案（lead 2026-10-18 晚确认；根因**不是**实现缺陷，也**不是**探针串扰）

**根因：验证脚本就地修改了共享工作树。**

qq-core 上一轮为验证"新用例咬不咬得住"，写了临时脚本**直接改写
`qq/core/worker.py` / `policy.py` → 跑测试 → 再写回**，每次改坏的窗口约 12 秒
（最后一次 19:00:30–19:03）。我的两个探针恰好在那两个窗口里跑，
于是**读到了处于突变状态的源码**：

| 我观察到的失败 | 当时树里实际是什么 | 对应突变 |
|----------------|---------------------|----------|
| `t_stop_during_generation`：got `SENT` / want `STOPPED`（该不发却发了） | 生成前那道 STOP 检查被临时删掉 | M16a |
| `t_context_only_still_recorded`：发出 `'好的'`、`call_count=1`、state `SENT` | `DEFAULT_PLAIN_MODE` 被临时改成 `'all'` | M07d |

证据链：
- **时间吻合**：我记录到 `worker.py` mtime **19:02:54**、`policy.py` mtime **19:04:08**——
  正落在失败窗口内，而我 18:59 记下的哈希与 19:04 之后重新读到的哈希**完全一致**，
  说明那两秒里文件被"改写又写回"，内容回到原样（所以我一度以为"代码没变"，这正是最迷惑人的地方）。
- **症状逐字一致**：qq-core 在**副本目录**里重放这两个突变，再用我的 v4 探针跑，
  复现出的 got/want 与我的报告一字不差。
- **时序吻合**：失败只出现在那 ~12 秒窗口内的两次运行；窗口之后
  累计 **77 次连跑全绿**（含 4 进程并发 16 次）+ 加护栏后 20/20 全绿。

**为什么值得留档（给以后的人）**：
1. **验证脚本绝不能原地改被验证对象**。想验证"测试咬不咬得住"，必须像我这样
   **整棵树复制到独立目录**再注入故障（`verify_qq/mutations/<编号>/`，`src/` 用只读符号链接）。
   就地改共享工作树 = 让**所有并行读者的观测都不再可信**，而且极其难查。
2. **非原子写 + 并发读者 = 读到撕裂/半成品源码**。`Path.write_text` 不是原子的：
   读者可能在任意字节处读到半个文件。**正确做法是先写临时文件再 `os.replace`**
   （本项目 `atomic_json` 对所有**数据文件**都做对了，但对**源码**没有 —— 因为源码本来就不该被脚本改）。
3. **"哈希没变"不等于"没被动过"**：mtime 变了、哈希没变，恰恰是"改写又写回"的指纹。
   下次遇到"同一份代码有时红有时绿"，先查 `stat` 的 mtime 与失败时间窗是否重合。
4. 这次能定案，靠的是三样东西：**mtime + 失败时间窗**、**我自己的突变副本当历史快照**、
   以及**排除了所有其他可能**（串扰审计、隔离护栏、77 次不复现）。

### F.3 顺带覆盖：qq-core 本轮修掉的一个"少发"真问题（我先前没找到）

`src/quota.merge_payloads` 是"**新 payload 的顶层字段赢**"，而 `action`/`priority` 原来只记在顶层 ——
于是同会话里"刚被 @（reply / 优先级 0）"与"紧随其后的一句闲聊（context_only / 优先级 2）"
合并后，顶层 `action` 被闲聊覆盖成 `context_only`，**那条 @ 就永远不回了**（只进时间线）。
修法：消息级 `wants_reply`/`wants_priority` + worker 取整批最紧急者（`_merge_priority`）。

我在 v4 里补了一组端到端探针钉住它（`§6.5 同会话合并`，5 个新用例）：

| 场景 | 断言 | 结果 |
|------|------|------|
| 先 @ 后闲聊（合并） | 必须回，**恰好 1 条**；模型只调 1 次；两条消息都在模型上下文里；按 @ 优先级记账不污染 plain 账本；再跑循环不重复回 | PASS |
| 先闲聊后 @（合并） | 同样必须回且只回 1 条 | PASS |
| 两条 @ 合并 | 只回 1 条（合并绝不能变成回两遍） | PASS |
| 两句闲聊合并 | 一条都不发、不调模型、但两条都进时间线 | PASS |
| 合并批的优先级 | 取最紧急者（@ 优先于闲聊） | PASS |

## G. 复现命令

```bash
# 全部套件（约 3 分钟）
MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu-24.04 -- bash -lc \
  'cd /mnt/d/AgentPrograms/wechat-bot && bash verify_qq/final_pass.sh'

# 突变测试（约 7 分钟，25 个突变）
MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu-24.04 -- bash -lc \
  'cd /mnt/d/AgentPrograms/wechat-bot && python3 -u verify_qq/v6_mutation.py'

# 单探针隔离（排查用）
MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu-24.04 -- bash -lc \
  'cd /mnt/d/AgentPrograms/wechat-bot && python3 verify_qq/_isolate.py t_stop_during_generation'
```

## H. 本轮我改过哪些文件

仍然**只改 `verify_qq/**`**（v1/v2/v3/v4/v8 的断言 + 新增几个排查脚本
`_isolate.py` / `_make_v4_debug.py` / `_v4_debug.py` / `_v4_loop.sh` / `_v4_repeat.sh` /
`_v4_stress.sh` / `_diff_snapshots.sh` / `_run_suites.sh` / `_probe_stop*.py`）。
没有碰 `qq/**`、`src/**`、`wsl/**`、`config/**`、任何 `test_*.py`；未执行任何 git 命令。
启用 `_isolate.py` 只需读取自己的 v4 副本，不产生仓库副作用。

