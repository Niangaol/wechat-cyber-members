#!/bin/bash
export DISPLAY=:99
for id in 0xe00010 0xc001c2 0xc001c3 0xc001c4 0x1000003; do
  state=$(xwininfo -id $id 2>/dev/null | grep 'Map State' | tr -d ' ')
  import -window $id /tmp/w_$id.png 2>/tmp/err_$id.txt
  rc=$?
  sz=$(stat -c%s /tmp/w_$id.png 2>/dev/null)
  err=$(head -c 80 /tmp/err_$id.txt | tr '\n' ' ')
  echo "id=$id $state import_rc=$rc size=$sz err=[$err]"
done
