#!/bin/bash
export DISPLAY=:99
echo "=== 点测试群名称区（窗口内 160,130 → 绝对 273,161）==="
timeout 10 xdotool mousemove 273 161
timeout 10 xdotool click 1
sleep 3
import -window 14680080 /tmp/main-sel.png
python3 - <<'PY'
import subprocess, json
out = subprocess.run(['tesseract','/tmp/main-sel.png','stdout','-l','chi_sim+eng','--psm','6'],
                     capture_output=True, text=True, timeout=60).stdout
lines = [l.strip() for l in out.splitlines() if l.strip()][:4]
print(json.dumps({'top_lines': lines}, ensure_ascii=False))
PY
cp /tmp/main-sel.png /mnt/d/AgentPrograms/wechat-bot/wsl/main-selected.png
