#!/usr/bin/env bash
# 最终确认：被验证快照的指纹 + 全部验证套件一次性跑完。
cd "$(dirname "$0")/.." || exit 1
echo "########## 时间 ##########"
date
echo
echo "########## 被验证快照（sha256） ##########"
sha256sum qq/core/*.py qq/bot.py qq/plugins/*.py
echo "--- 被验证的测试文件 ---"
sha256sum test_qq_core.py test_qq_core_policy.py test_qq_plugin.py test_qq_deploy.py test_qq_shared_state.py
echo
echo "########## 0. 现有测试基线 ##########"
python3 -m unittest test_qq_core test_qq_core_policy test_qq_plugin test_qq_deploy test_qq_shared_state 2>&1 | tail -4
echo
for script in v1_envelope v2_policy v3_media v4_service v5_integration v7_weak_tests v8_survivor_probe; do
    echo "########## $script ##########"
    python3 "verify_qq/$script.py" 2>&1 | tail -6
    echo
done
echo "########## v6 突变测试结论 ##########"
grep -E "杀死|存活|突变测试结果" verify_qq/mutation-report.txt | tail -32
