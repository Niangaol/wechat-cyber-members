
"""
剪贴板层：发文字/图片的银弹
为什么重要：WSLg 里给中文 App 打字是老大难（输入法框架全是坑），
但"写剪贴板 + Ctrl+V"在任何 GUI 上都成立——机器人发的文字本来就是程序生成的，
走剪贴板粘贴 100% 稳定，还顺带解决特殊字符/换行/emoji
主用 xsel（写完即退，不 daemon 化）；xclip 作兜底（Popen 不等）
"""
from __future__ import annotations

import subprocess


def _popen(cmd: list, stdin_bytes: bytes = None):
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def set_text(text: str) -> bool:
    """把文字写入剪贴板"""
    # xsel：前台工具，写完就退，不会挂
    r = subprocess.run(
        ["xsel", "--clipboard", "--input"],
        input=text.encode("utf-8"), capture_output=True, timeout=10,
    )
    if r.returncode == 0:
        return True
    # 兜底 xclip：必须 Popen 不等待（它 fork 守护进程持有剪贴板内容）
    try:
        p = _popen(["xclip", "-selection", "clipboard"])
        p.stdin.write(text.encode("utf-8"))
        p.stdin.close()
        return True
    except Exception:
        return False


def set_image(path: str) -> bool:
    """把图片文件写入剪贴板（之后 Ctrl+V 即可粘贴到微信输入框）"""
    with open(path, "rb") as f:
        data = f.read()
    # xsel 不支持图片 MIME；图片必须由 xclip 持有 image/png selection。
    try:
        p = _popen(["xclip", "-selection", "clipboard", "-t", "image/png"])
        p.stdin.write(data)
        p.stdin.close()
        return True
    except Exception:
        return False


def get_text() -> str:
    """读剪贴板文字（调试用）"""
    r = subprocess.run(
        ["xsel", "--clipboard", "--output"],
        capture_output=True, text=True, timeout=10,
    )
    return r.stdout.strip() if r.returncode == 0 else ""


if __name__ == "__main__":
    # 自测：python3 clipboard.py
    ok = set_text("机器人测试 123")
    print("写入:", ok, "| 读回:", get_text() if ok else "-")
