"""WSL 内视觉兜底代理：截图(:99) → step-5 看图决策 → xdotool 执行。

只操作 DISPLAY=:99 的虚拟屏，绝不触碰 Windows。动作集与安全边界：
- click/double_click: 图像像素坐标（与屏幕绝对坐标 1:1）
- hotkey: xdotool key 组合键（如 ctrl+v）
- type: 仅 ASCII 短文本（CJK 必须走剪贴板+hotkey ctrl+v）
- done / fail: 结束
每次截图后都把当前步号与截图文件路径写进提示词；超过 --max-steps 强制结束。
"""
import base64
import io
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/mnt/d/AgentPrograms/wechat-bot")
sys.path.insert(0, str(ROOT / "src"))
from multimodal import StepPlan, image_data, parse_json  # noqa: E402


def sh(args, timeout=25):
    return subprocess.run(args, capture_output=True, timeout=timeout, check=True).stdout


def screenshot(path):
    sh(["bash", "-c", "import -window root " + str(path)])
    return path


def execute(action):
    kind = action.get("action")
    if kind == "click":
        sh(["xdotool", "mousemove", str(action["x"]), str(action["y"])]), time.sleep(0.3)
        sh(["xdotool", "click", "1"])
    elif kind == "double_click":
        sh(["xdotool", "mousemove", str(action["x"]), str(action["y"])]), time.sleep(0.3)
        sh(["xdotool", "click", "--repeat", "2", "--delay", "120", "1"])
    elif kind == "hotkey":
        sh(["xdotool", "key", "--clearmodifiers", action["keys"]])
    elif kind == "type":
        sh(["xdotool", "type", "--clearmodifiers", action["text"]])
    elif kind == "scroll":
        sh(["xdotool", "click", str(4 if action.get("direction") == "up" else 5)])
    else:
        raise ValueError("unknown action " + str(kind))
    time.sleep(1.2)


SYSTEM = ("你在远程操控一台 Linux 电脑的屏幕（分辨率 1280x800）。"
          "看当前屏幕截图，输出下一个动作。只输出 JSON 对象，格式："
          '{"action":"click","x":整数像素,"y":整数像素} 或 {"action":"double_click",...} 或 '
          '{"action":"hotkey","keys":"ctrl+v"} 或 {"action":"type","text":"ASCII"} 或 '
          '{"action":"scroll","direction":"up|down"} 或 {"action":"done"} 或 {"action":"fail","reason":"..."}。'
          "坐标用截图里的真实像素。任务完成就 done；无法完成就 fail。不要输出解释。")


def main():
    task = sys.argv[1]
    max_steps = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    plan = StepPlan(json.loads((ROOT / "config" / "resident.json").read_text()))
    trace = []
    for step in range(1, max_steps + 1):
        path = f"/tmp/vision-agent-{step}.png"
        screenshot(path)
        with open(path, "rb") as handle:
            b64 = base64.b64encode(handle.read()).decode()
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
                {"type": "text", "text": f"任务：{task}\n这是第 {step}/{max_steps} 步前的截图。"}]},
        ]
        raw = plan.call(messages, max_tokens=300)
        action = parse_json(raw)
        trace.append({"step": step, "action": action})
        print(json.dumps({"step": step, "action": action}, ensure_ascii=False), flush=True)
        if action.get("action") == "done":
            print(json.dumps({"final": "done", "trace": trace}, ensure_ascii=False))
            return 0
        if action.get("action") == "fail":
            print(json.dumps({"final": "fail", "reason": action.get("reason"), "trace": trace},
                             ensure_ascii=False))
            return 2
        execute(action)
    print(json.dumps({"final": "max_steps", "trace": trace}, ensure_ascii=False))
    return 3


if __name__ == "__main__":
    sys.exit(main())
