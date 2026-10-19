#!/usr/bin/env bash
# 并发跑多份带探针的 v4，制造 CPU 竞争以复现时序抖动；命中就打印失败上下文。
cd "$(dirname "$0")/.." || exit 1
python3 verify_qq/_make_v4_debug.py >/dev/null || exit 1
round=0
while [ "$round" -lt 4 ]; do
    round=$((round + 1))
    rm -f /tmp/v4stress-*.log
    pids=""
    for k in 1 2 3 4; do
        ( python3 verify_qq/_v4_debug.py >/tmp/v4stress-$k.log 2>&1 ) &
        pids="$pids $!"
    done
    for p in $pids; do wait "$p"; done
    hit=0
    for k in 1 2 3 4; do
        if grep -q '\[FAIL\]' "/tmp/v4stress-$k.log"; then
            hit=1
            echo "轮次 $round 的第 $k 份挂了："
            grep -E 'DECIDE|\[FAIL\]|验证：共' "/tmp/v4stress-$k.log" | tail -30
            echo "---- 该份的失败上下文（前后 12 行）----"
            grep -B12 '\[FAIL\]' "/tmp/v4stress-$k.log" | head -40
        fi
    done
    if [ "$hit" = "1" ]; then
        exit 0
    fi
    echo "轮次 $round：4 份全绿"
done
echo "反压 16 次都没复现"
