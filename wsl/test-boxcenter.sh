#!/bin/bash
cd /mnt/d/AgentPrograms/wechat-bot
python3 -m py_compile wsl/uitars-agent.py && echo COMPILE_OK
python3 - <<'PY'
import importlib.util
spec = importlib.util.spec_from_file_location("ua", "/mnt/d/AgentPrograms/wechat-bot/wsl/uitars-agent.py")
ua = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ua)
print("normal:", ua.box_center("(500,500)"))
print("oob:   ", ua.box_center("(1352,570)"))
print("neg:   ", ua.box_center("(-50,1200)"))
print("box:   ", ua.box_center("[100,200,300,400]"))
print("bad:   ", ua.box_center("garbage"))
PY
