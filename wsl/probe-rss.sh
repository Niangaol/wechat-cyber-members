#!/bin/bash
# 探测多个 RSSHub 公共实例 + 备选热榜 API
probe() {
    CODE=$(curl -s -o /tmp/rss-body.txt -w "%{http_code}" --max-time 20 -A "Mozilla/5.0" "$1" 2>/dev/null)
    SIZE=$(stat -c%s /tmp/rss-body.txt 2>/dev/null || echo 0)
    echo "HTTP $CODE  size=$SIZE  $1"
    [ "$CODE" = "200" ] && [ "$SIZE" -gt 500 ] && echo "  >>> 可用"
}
probe "https://rsshub.app/weibo/search/hot"
probe "https://rsshub.rssforever.com/weibo/search/hot"
probe "https://rsshub.pseudoyu.com/weibo/search/hot"
probe "https://rsshub.injahow.workers.dev/weibo/search/hot"
probe "https://api.vvhan.com/api/hotlist/wbHot"
probe "https://api.vvhan.com/api/hotlist/zhihuHot"
