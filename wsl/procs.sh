#/bin/bash
ps -eo pid,ppid,etime,cmd | grep -iE "wechat|weixin" | grep -v grep | head -12
echo ---
systemctl --user list-units --all | grep -iE "wechat|weixin"
