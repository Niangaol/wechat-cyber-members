#!/bin/bash
probe() {
    CODE=$(curl -s -o /tmp/rss-body2.txt -w "%{http_code}" --max-time 15 -A "Mozilla/5.0" "$1" 2>/dev/null)
    SIZE=$(stat -c%s /tmp/rss-body2.txt 2>/dev/null || echo 0)
    if [ "$CODE" = "200" ] && [ "$SIZE" -gt 500 ]; then
        echo "[可用] $1 (size=$SIZE)"
    else
        echo "[不可用] HTTP $CODE $1"
    fi
}
probe "https://rsshub.ktachibana.party/weibo/search/hot"
probe "https://rsshub.speednet.icu/weibo/search/hot"
probe "https://rsshub.woodland.cafe/weibo/search/hot"
probe "https://rsshub.condy.app/weibo/search/hot"
probe "https://rsshub.anyant.com/weibo/search/hot"
probe "https://rsshub.aqz.icu/weibo/search/hot"
probe "https://60s.life/v2/weibo/hot"
probe "https://api.oioweb.cn/api/common/HotList"
