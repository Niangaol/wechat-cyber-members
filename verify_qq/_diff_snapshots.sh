#!/usr/bin/env bash
# 用我自己的突变副本当历史快照，判断 qq/core 在验证期间有没有真的变过内容。
cd "$(dirname "$0")/.." || exit 1
for snap in mutations/M01 mutations/_baseline; do
    echo "=== 快照 verify_qq/$snap （突变运行时的拷贝）==="
    for f in policy.py worker.py envelope.py config.py service.py media.py store.py bridge.py; do
        if [ -f "verify_qq/$snap/qq/core/$f" ]; then
            if cmp -s "verify_qq/$snap/qq/core/$f" "qq/core/$f"; then
                echo "  一致   $f"
            else
                echo "  有差异 $f"
            fi
        fi
    done
done
echo
echo "=== 各副本里 policy.py 的关键行为标记（看当时是不是旧版）==="
grep -c "_safe_mode" verify_qq/mutations/M01/qq/core/policy.py
grep -c "_safe_mode" verify_qq/mutations/_baseline/qq/core/policy.py
grep -c "_safe_mode" qq/core/policy.py
echo "=== worker.py 是否已有 confirmed=False ==="
grep -c "confirmed=False" verify_qq/mutations/M01/qq/core/worker.py
grep -c "confirmed=False" qq/core/worker.py
echo "=== envelope.py 是否已 lower 参数键 ==="
grep -c "lower()" verify_qq/mutations/M01/qq/core/envelope.py
grep -c "lower()" qq/core/envelope.py
