#!/bin/bash
echo "--- listeners ---"
ss -ltnp 2>/dev/null | grep -E ':(6080|5900)' || echo "no 6080/5900 listener"
echo "--- http check ---"
curl -s -o /dev/null -w "novnc_http=%{http_code}\n" --noproxy '*' http://127.0.0.1:6080/vnc.html
curl -s -o /dev/null -w "websockify=%{http_code}\n" --noproxy '*' http://127.0.0.1:6080/websockify
echo "--- procs ---"
pgrep -a -f 'x11vnc|websockify|Xvfb|openbox' | sed 's/ --.*//' | head -10
