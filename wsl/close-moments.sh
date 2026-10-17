#/bin/bash
export DISPLAY=:99
xdotool windowclose 14682371
sleep 3
if xdotool search --name "^Moments$" | grep -q .; then
  echo "still open, force"
  for w in $(xdotool search --name "^Moments$"); do xdotool windowclose $w; done
  sleep 2
fi
xdotool search --onlyvisible --class wechat | while read wid; do
  geo=$(xdotool getwindowgeometry --shell "$wid" | tr "\n" " ")
  name=$(xdotool getwindowname "$wid" 2>/dev/null | head -1)
  echo "wid=$wid name=$name $geo"
done
