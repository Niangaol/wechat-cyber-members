
"""
截图层：在 WSLg 里截微信窗口
路线已实测验证：XWayland 窗口树里能找到 Weixin 窗口，用 ImageMagick import 按窗口 ID 截
（grim 那套 wlroots 协议在 Weston 上用不了，xwd -root 也被拒，import -window <id> 是通的）
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


def _xwininfo_tree(display: str = ":0") -> str:
    """拿 X 窗口树文本（失败时抛异常，带 stderr）"""
    env = {"DISPLAY": display, "PATH": "/usr/bin:/bin:/usr/local/bin"}
    r = subprocess.run(
        ["xwininfo", "-root", "-tree"],
        capture_output=True, text=True, env=env, timeout=15,
    )
    if r.returncode != 0:
        raise RuntimeError("xwininfo 失败(rc=%d): %s" % (r.returncode, r.stderr.strip()))
    return r.stdout


def list_x_windows(display: str = ":0") -> list:
    """
    列出 X 窗口树里所有窗口
    返回 [{id, title, classes, w, h, x, y, abs_x, abs_y}, ...]

    xwininfo 行格式：
        0x600006 "Weixin": ("wechat" "wechat")  280x380+32+32  +1140+609
        0xa00004 (has no name): ()  1x1+-1+-1  +-1+-1
    """
    out = _xwininfo_tree(display)
    windows = []
    # 注意：标题组只匹配到冒号为止，左括号留给 classes 组（曾经在这里踩过坑）
    # 两种写法都要认：
    #   0xe00010 "Weixin": ("wechat" "wechat")  1021x740+0+0  +0+0
    #   0xa00004 (has no name): ()  1x1+-1+-1  +-1+-1      ← 匿名窗口，以前整行被跳过
    pat = re.compile(
        r'(0x[0-9a-f]+)\s+'
        r'(?:"([^"]*)":\s*)?'
        r'(?:\(has no name\):\s*)?'
        r'\(([^)]*)\)\s+'
        r'(\d+)x(\d+)\+(-?\d+)\+(-?\d+)\s+\+(-?\d+)\+(-?\d+)'
    )
    for m in pat.finditer(out):
        wid, title, classes, w, h, x, y, bx, by = m.groups()
        windows.append({
            "id": wid,
            "title": title or "",
            "classes": classes,
            "w": int(w), "h": int(h),
            "x": int(x), "y": int(y),
            "abs_x": int(bx), "abs_y": int(by),
        })
    return windows


def find_wechat_windows(display: str = ":0") -> dict:
    """
    找微信的两个关键窗口：
    - client: Weixin 客户区（登录后是主界面）
    - frame:  带边框的框架窗口（截图用这个，完整）
    """
    wins = list_x_windows(display)
    client = None
    for w in wins:
        if "Weixin" in w["title"] or "wechat" in w["classes"].lower():
            if client is None or w["w"] * w["h"] > client["w"] * client["h"]:
                client = w
    frame = None
    if client:
        for w in wins:
            contains = (w["abs_x"] <= client["abs_x"] and w["abs_y"] <= client["abs_y"]
                        and w["abs_x"] + w["w"] >= client["abs_x"] + client["w"]
                        and w["abs_y"] + w["h"] >= client["abs_y"] + client["h"])
            smaller_than_screen = w["w"] * w["h"] < 3840 * 2160
            not_same = (w["w"], w["h"]) != (client["w"], client["h"])
            if contains and smaller_than_screen and not_same:
                if frame is None or w["w"] * w["h"] < frame["w"] * frame["h"]:
                    frame = w
    return {"frame": frame, "client": client}


def screenshot_window(window_id: str, out_path: str, display: str = ":0") -> str:
    """按窗口 ID 截图（import -window，实测可用）"""
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    env = {"DISPLAY": display, "PATH": "/usr/bin:/bin:/usr/local/bin"}
    r = subprocess.run(
        ["import", "-window", window_id, out_path],
        capture_output=True, text=True, env=env, timeout=30,
    )
    if r.returncode != 0 or not Path(out_path).exists():
        raise RuntimeError("截图失败: " + r.stderr.strip())
    return out_path


def screenshot_wechat(out_path: str = "/tmp/wechat-bot/wechat.png", display: str = ":0") -> str:
    """截微信当前窗口（自动找窗口 ID）"""
    wins = find_wechat_windows(display)
    target = wins.get("frame") or wins.get("client")
    if not target:
        raise RuntimeError("找不到微信窗口（微信启动了吗？）")
    return screenshot_window(target["id"], out_path, display)


if __name__ == "__main__":
    # 自测：python3 screen.py
    try:
        wins = find_wechat_windows()
        print("找到窗口:", {k: (v["id"] if v else None) for k, v in wins.items()})
        p = screenshot_wechat()
        print("截图保存:", p)
    except Exception as e:
        print("失败:", e)
