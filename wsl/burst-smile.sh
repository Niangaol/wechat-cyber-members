#!/bin/bash
export DISPLAY=:99
W=14680080
echo "=== 点笑脸后每 250ms 连拍 8 张 ==="
xdotool mousemove 312 605 click 1
for i in 1 2 3 4 5 6 7 8; do
  import -window $W /tmp/burst-$i.png 2>/dev/null
  sleep 0.25
done
python3 - <<'PY'
import hashlib, json
hs = []
for i in range(1, 9):
    try:
        hs.append(hashlib.sha256(open('/tmp/burst-%d.png'%i,'rb').read()).hexdigest()[:10])
    except Exception:
        hs.append('ERR')
print(json.dumps({'burst_hashes': hs, 'any_change': len(set(hs)) > 1}, ensure_ascii=False))
# 对比点击前的基线
base = hashlib.sha256(open('/tmp/r35.png','rb').read()).hexdigest()[:10]
print(json.dumps({'baseline': base, 'differs_from_baseline': [h != base for h in hs]}))
PY
