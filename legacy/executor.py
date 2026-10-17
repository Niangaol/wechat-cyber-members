
"""
执行器抽象层：机器人系统的"手"
- XDoToolExecutor：默认实现，用 xdotool 操作 XWayland 窗口（需 apt install xdotool）
- CustomExecutor：适配年糕自己的 WSL 操作工具，配 3 条命令即可接入
所有上层模块（wechat_ops 等）只依赖抽象接口，换手不用改业务代码
"""
from __future__ import annotations

import shlex
import subprocess
import time
from abc import ABC, abstractmethod

from models import Action


class BaseExecutor(ABC):
    """执行器接口——所有实现必须提供这 7 个原语"""

    @abstractmethod
    def click(self, x: int, y: int) -> None: ...

    @abstractmethod
    def double_click(self, x: int, y: int) -> None: ...

    @abstractmethod
    def right_click(self, x: int, y: int) -> None: ...

    @abstractmethod
    def type_text(self, text: str) -> None: ...

    @abstractmethod
    def hotkey(self, keys: str) -> None: ...

    @abstractmethod
    def scroll(self, x: int, y: int, direction: str = "down") -> None: ...

    @abstractmethod
    def drag(self, x1: int, y1: int, x2: int, y2: int) -> None: ...


class XDoToolExecutor(BaseExecutor):
    """xdotool 实现（WSLg/XWayland 下可用）"""

    def __init__(self, display: str = ":0"):
        self.display = display
        self.env = {"DISPLAY": display, "PATH": "/usr/bin:/bin:/usr/local/bin"}

    def _run(self, args: list) -> None:
        r = subprocess.run(args, capture_output=True, text=True, env=self.env, timeout=20)
        if r.returncode != 0:
            raise RuntimeError("xdotool 失败: " + r.stderr.strip())

    def click(self, x: int, y: int) -> None:
        self._run(["xdotool", "mousemove", str(x), str(y), "click", "1"])

    def double_click(self, x: int, y: int) -> None:
        self._run(["xdotool", "mousemove", str(x), str(y),
                   "click", "1", "click", "1", "--delay", "80"])

    def right_click(self, x: int, y: int) -> None:
        self._run(["xdotool", "mousemove", str(x), str(y), "click", "3"])

    def type_text(self, text: str) -> None:
        # xdotool type 对中文支持差，中文走剪贴板粘贴（见 clipboard.py）
        # 这里只负责 ASCII 直打
        self._run(["xdotool", "type", "--delay", "20", "--", text])

    def hotkey(self, keys: str) -> None:
        self._run(["xdotool", "key", keys])

    def scroll(self, x: int, y: int, direction: str = "down") -> None:
        btn = "5" if direction == "down" else "4"
        self._run(["xdotool", "mousemove", str(x), str(y), "click", btn])

    def drag(self, x1: int, y1: int, x2: int, y2: int) -> None:
        self._run(["xdotool", "mousemove", str(x1), str(y1),
                   "mousedown", "1", "sleep", "0.1",
                   "mousemove", "--sync", str(x2), str(y2),
                   "mouseup", "1"])


class CustomExecutor(BaseExecutor):
    """
    适配年糕自己的 WSL 操作工具
    配置 3 条命令模板（config.toml [executor] 节）：
      custom_click = "/path/to/tool click {x} {y}"
      custom_type  = "/path/to/tool type {text}"     # 文字/中文都走这里
      custom_key   = "/path/to/tool key {key}"
    未配的命令回退到 xdotool
    """

    def __init__(self, templates: dict, display: str = ":0"):
        self.tpl = templates or {}
        self.fallback = XDoToolExecutor(display)

    def _cmd(self, key: str, **kw) -> list:
        tpl = self.tpl.get(key)
        if not tpl:
            return None
        return shlex.split(tpl.format(**kw))

    def _exec(self, key: str, **kw) -> bool:
        cmd = self._cmd(key, **kw)
        if not cmd:
            return False
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.returncode == 0

    def click(self, x: int, y: int) -> None:
        if not self._exec("custom_click", x=x, y=y):
            self.fallback.click(x, y)

    def double_click(self, x: int, y: int) -> None:
        if not self._exec("custom_double", x=x, y=y):
            self.fallback.double_click(x, y)

    def right_click(self, x: int, y: int) -> None:
        if not self._exec("custom_right", x=x, y=y):
            self.fallback.right_click(x, y)

    def type_text(self, text: str) -> None:
        if not self._exec("custom_type", text=text):
            self.fallback.type_text(text)

    def hotkey(self, keys: str) -> None:
        if not self._exec("custom_key", key=keys):
            self.fallback.hotkey(keys)

    def scroll(self, x: int, y: int, direction: str = "down") -> None:
        self.fallback.scroll(x, y, direction)

    def drag(self, x1: int, y1: int, x2: int, y2: int) -> None:
        self.fallback.drag(x1, y1, x2, y2)


def make_executor(cfg: dict) -> BaseExecutor:
    """工厂：按 config.toml [executor] 造执行器"""
    display = cfg.get("wechat", {}).get("display", ":0")
    if cfg.get("executor", {}).get("type") == "custom":
        return CustomExecutor(cfg["executor"], display)
    return XDoToolExecutor(display)
