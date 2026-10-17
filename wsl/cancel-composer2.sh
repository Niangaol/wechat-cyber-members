#/bin/bash
export DISPLAY=:99
WID=$(xdotool search --onlyvisible --name "^Moments$" | head -1)
[ -z "$WID" ] && { echo NO_MOMENTS; exit 1; }
echo "moments wid=$WID"
xdotool windowraise "$WID"
xdotool windowfocus "$WID"
sleep 0.5
# Cancel 按钮随内容高度浮动：扫下半屏灰色 Cancel（浅灰底深灰字）不可靠，直接试两个已知位置
xdotool mousemove 698 601
sleep 0.3
xdotool click 1
sleep 2
import -window "$WID" /tmp/cancel-a.png
echo done
