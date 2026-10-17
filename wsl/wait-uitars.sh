#!/bin/bash
for i in $(seq 1 60); do
  R=$(curl -s -w "|%{http_code}" --max-time 5 http://127.0.0.1:8088/v1/models 2>/dev/null)
  CODE="${R##*|}"
  if [ "$CODE" = "200" ]; then
    echo "READY after about $((i*3))s"
    echo "${R%|*}"
    exit 0
  fi
  sleep 3
done
echo "STILL LOADING after 180s"
echo "--- server log tail ---"
tail -25 /tmp/uitars-server/server.log
exit 1
