#!/bin/bash
echo "--- WSL 视角的 8088 ---"
timeout 5 curl -s -o /dev/null -w "127.0.0.1:8088 -> %{http_code}
" http://127.0.0.1:8088/v1/models 2>&1 || echo "127.0.0.1 不通"
HOSTIP=$(ip route show default 2>/dev/null | awk '{print $3; exit}')
echo "windows host ip: $HOSTIP"
[ -n "$HOSTIP" ] && timeout 5 curl -s -o /dev/null -w "$HOSTIP:8088 -> %{http_code}
" http://$HOSTIP:8088/v1/models 2>&1 || echo "host ip 不通"
echo "--- resolv.conf ---"
grep nameserver /etc/resolv.conf 2>/dev/null
echo "--- 模型列表 ---"
timeout 8 curl -s http://127.0.0.1:8088/v1/models 2>/dev/null | head -c 400
echo
[ -n "$HOSTIP" ] && timeout 8 curl -s http://$HOSTIP:8088/v1/models 2>/dev/null | head -c 400
echo
