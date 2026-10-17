#!/bin/bash
export DISPLAY=:99
echo "=== 窗口 ==="
for w in $(xdotool search --name ".*" 2>/dev/null); do
  n=$(xdotool getwindowname $w 2>/dev/null)
  g=$(xdotool getwindowgeometry $w 2>/dev/null | grep Geometry | tr -d ' ')
  case "$n" in Weixin|Moments|Open) echo "$w | $n | $g";; esac
done
echo "=== 主窗口标题 OCR（验证群聊还在）==="
import -window 14680080 /tmp/main-title.png 2>/dev/null
python3 - <<'PY'
import subprocess, json
out = subprocess.run(['tesseract','/tmp/main-title.png','stdout','-l','chi_sim+eng','--psm','6'],
                     capture_output=True, text=True, timeout=60).stdout
first = [l for l in out.splitlines() if l.strip()][:3]
print(json.dumps({'title_area': first}, ensure_ascii=False))
PY
echo "=== 服务与账本 ==="
systemctl --user is-active wechat-bot wechat-stack 2>&1 | tr '\n' ' '; echo
python3 /mnt/d/AgentPrograms/wechat-bot/wsl/ledger-report.py 2>&1 | head -6
echo "=== llama-server ==="
pgrep -f llama-server >/dev/null && echo RUNNING || echo DEAD
