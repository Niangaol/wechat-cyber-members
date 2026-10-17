# 调研精华：微信 UI 自动化路线（2026-10-15）

完整报告：`/d/AgentPrograms/wechat-gui-automation-research.md`（24084 字符，含全部链接）
本文只记**对本项目有决策价值**的结论。

## 1. 同型开源项目（Linux 官方微信 + GUI 自动化，路线已验证）

| 项目 | 明星借鉴点 |
|---|---|
| linux-wechat-on-muse | **读消息走 SQLite WAL tail**（不截图 OCR！）+ 单一发送器 sendd_v2.py + 发送后 WAL 回读验证送达 |
| AgInTi-LabCanvas | **发送前 OCR 聊天窗口标题**和目标比对，防发错群（GUI 自动化最大事故） |
| openclaw-wechat-automation | XDND v5 拖拽发图片/文件（比剪贴板稳）；像素颜色定位 UI（发送按钮绿 RGB(8,195,99)）；微信 Linux 4.x 窗口布局表 |

## 2. 本机地基实测结论（2026-10-15，全部通过）

- 截图：`import -window <窗口ID>`（ImageMagick）✓（WSLg 和 Xvfb 上都通）
- 键鼠：**XTest 分场景**——鼠标移动生效 ≠ 点击/键盘生效。WSLg 登录窗点击实测失败；
  主窗口键盘必须 `xdotool key --window <真实窗口ID> --clearmodifiers` 定向发送才灵。
  **2026-10-16 起架构迁到 Xvfb :99**（WSLg 窗口无法渲染进 RDP 会话，mirrored 模式实测无效），
  Xvfb 上 XTest 原生可靠，不存在 WSLg 的 libei 问题
- 剪贴板：**文字用 xsel；图片必须 xclip**（xsel 没有 --type 选项，写 image/png 会静默失败！
  2026-10-15 实测踩坑）。xclip 要 Popen 后立即关 stdin 不能 wait（fork daemon 持有剪贴板）
- 中文输入：剪贴板粘贴是唯一正解（`xdotool type` 不支持 CJK，全部项目一致结论）✓
- 微信在 Xvfb 上启动即退（exit 0 零输出）的真因：**Xvfb 僵尸 X selection**，
  重启 Xvfb 解决；保活必须两级恢复（见 wsl/stack-main.sh）

## 3. 功能实现路径（按难度排序，从易到难）

1. **文字/网页链接**：点会话 → 剪贴板粘贴 → 回车（最简单，先做）
2. **表情包**：工具栏 y490-560 区域点表情面板 → 选目标
3. **图片**：XDND 拖拽（openclaw 方案）或剪贴板 `xsel --type image/png` + Ctrl+V
4. **@**：输入框敲 @ → 弹成员列表 → 点选
5. **拍一拍**：双击聊天记录里对方头像 → 菜单点"拍一拍"
6. **发朋友圈**（最难）：autopyq 四段模板法适配 Linux——
   左侧"发现"→朋友圈入口 → 朋友圈窗口相机按钮（**发文字要长按相机图标**，发图单击）→ 编辑区粘贴文案 → 点"发表"
   ⚠️ 451 星的 wechatauto-replica 明确**舍弃** GUI 发朋友圈（4.x 发表是自绘界面，不可靠）；必须配：发布前后截图留存、小号、低频、人工确认闸

## 4. 稳定性铁律（从 10+ 个项目提炼）

- **发送前读回校验**：回车前把输入框内容读回来和待发内容比对，"送给空气"时一次回车都不发
- **OCR 标题闸**：发送前识别当前聊天窗口标题，和目标会话不一致就拦下
- **窗口永不移动不缩放**（移动会让标定坐标全废）；用窗口相对坐标
- **剪贴板卫生**：用前快照、用完还原（usechat 方案），防止抢用户的剪贴板
- **拟人化**：正态分布随机延迟、曲线鼠标 + ±2px 抖动、阅读停顿（wxbot-automation）
- **machine-id/hostname 钉死 + 固定出口 IP**（微信挑设备，muse 的 ensure-deps.sh）
- **.wslconfig 加 maxCrashDumpCount=1**（微信崩溃转储单份近 1GB，默认留 10 份）
- **失败要显式**：OCR 不准时明确失败，不要静默盲点坐标

## 5. 待验证项（登录后逐条确认）

- [ ] 左侧栏有没有"朋友圈"Tab（决定发朋友圈功能可行性）
- [ ] ~/.xwechat 下 SQLite 数据库结构（决定读消息能否走 WAL tail 路线）
- [ ] 表情面板/拍一拍菜单/@ 列表的实际坐标
- [ ] 群聊和私聊的界面差异

## 6. 已排除的路线（别再走弯路）

- deepin-wine：官方仓库已移除个人微信包（com.qq.weixin.deepin），路线死亡
- grim 截图：WSLg 是 Weston 合成器，grim 要 wlroots，不可用
- ydotool/uinput/evdev：WSL2 内核无 CONFIG_INPUT_UINPUT，走不通
- xclip 为主力剪贴板：daemon 化挂死 subprocess
