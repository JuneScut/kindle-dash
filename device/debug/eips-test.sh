#!/bin/sh
# 一次性测遍所有画图方式，把退出码写进 eips-test.txt
D=/mnt/us/kindle-todo
OUT="$D/eips-test.txt"
{
  echo "=== $(date) ==="
  echo "--- 1. eips -c 清屏 ---"
  eips -c; echo "rc=$?"
  sleep 1

  echo "--- 2. eips -g <file>  （正确顺序，无 -f）---"
  eips -g "$D/dash.png"; echo "rc=$?"
  sleep 1

  echo "--- 3. eips -g <file> -f （正确顺序，全刷）---"
  eips -g "$D/dash.png" -f; echo "rc=$?"
  sleep 1

  echo "--- 4. eips -g <file> -f -w 2 ---"
  eips -g "$D/dash.png" -f -w 2; echo "rc=$?"
  sleep 1

  echo "--- 5. fbink -q -g -f ---"
  /mnt/us/libkh/bin/fbink -q -g "$D/dash.png" -f; echo "rc=$?"
  sleep 1

  echo "--- 6. fbink -g 不加 -q ---"
  /mnt/us/libkh/bin/fbink -g "$D/dash.png"; echo "rc=$?"
  sleep 1

  echo "--- 7. 文件 ---"
  ls -l "$D/dash.png"
  echo "--- 8. PNG 头 ---"
  dd if="$D/dash.png" bs=1 count=33 2>/dev/null | od -An -tx1 | head -3
} > "$OUT" 2>&1
