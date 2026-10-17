
"""
微信机器人入口
当前阶段（微信未登录）：环境自检模式
  python3 src/main.py check    # 检查微信进程/窗口/截图/剪贴板是否就绪
登录后（echo 模式）：
  python3 src/main.py echo     # 监测新消息 -> 复读回去（验证全链路）
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import tomllib
import screen
import clipboard
from executor import make_executor
from llm import make_llm

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.toml"


def load_config() -> dict:
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def cmd_check(cfg: dict) -> int:
    """环境自检：逐项报告机器人赖以生存的组件状态"""
    print("=" * 46)
    print("微信机器人环境自检")
    print("=" * 46)
    ok = True

    # 1) 微信进程（本程序就跑在 WSL 里，直接 pgrep）
    r = subprocess.run(
        ["pgrep", "-c", "-f", "RadiumWMPF"],
        capture_output=True, text=True,
    )
    n = r.stdout.strip()
    print(f"[{'OK' if n and n != '0' else '!!'}] 微信进程: {n or '0'} 个 (RadiumWMPF)")
    ok = ok and bool(n) and n != "0"

    # 2) 窗口
    try:
        wins = screen.find_wechat_windows()
        c = wins.get("client")
        f = wins.get("frame")
        print(f"[{'OK' if c else '!!'}] 微信窗口: client={c['id'] if c else None} frame={f['id'] if f else None}")
        ok = ok and bool(c)
    except Exception as e:
        print(f"[!!] 找窗口失败: {e}")
        ok = False

    # 3) 截图
    try:
        p = screen.screenshot_wechat(cfg["screen"]["save_dir"] + "/check.png")
        import os
        size = os.path.getsize(p)
        print(f"[{'OK' if size > 1000 else '!!'}] 截图: {p} ({size} 字节)")
        ok = ok and size > 1000
    except Exception as e:
        print(f"[!!] 截图失败: {e} (imagemagick 装了吗: sudo apt install imagemagick)")
        ok = False

    # 4) 剪贴板
    try:
        good = clipboard.set_text("自检测试")
        print(f"[{'OK' if good else '!!'}] 剪贴板: {'可用' if good else '不可用'}")
        ok = ok and good
    except Exception as e:
        print(f"[!!] 剪贴板失败: {e} (xclip 装了吗: sudo apt install xclip)")
        ok = False

    # 5) 执行器
    ex = make_executor(cfg)
    print(f"[OK] 执行器: {type(ex).__name__}")

    # 6) 大脑
    llm = make_llm(cfg)
    reply = llm.chat([{"role": "user", "content": "你好"}])
    print(f"[OK] 大脑: {type(llm).__name__} -> 回复 '{reply[:30]}'")

    print("=" * 46)
    print("自检结果:", "全部就绪" if ok else "有项目未通过，按上面提示修")
    return 0 if ok else 1


def main() -> int:
    cfg = load_config()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "check":
        return cmd_check(cfg)
    print(f"未知命令: {cmd} (可用: check)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
