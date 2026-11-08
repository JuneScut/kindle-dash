#!/bin/sh
# 诊断：把设备环境、fbink 能力、上次刷新的日志都倒到一个文件里，
# 插上电脑就能读，不用 SSH。
D=/mnt/us/kindle-todo
{
  echo "== date =="; date
  echo "== whoami =="; id
  echo "== fbink -e =="
  /mnt/us/libkh/bin/fbink -e 2>&1
  echo "== fbink version =="
  /mnt/us/libkh/bin/fbink -V 2>&1 | head -3
  echo "== eips =="
  command -v eips; eips 2>&1 | head -5
  echo "== files =="
  ls -l "$D" 2>&1
  echo "== refresh.log =="
  cat "$D/refresh.log" 2>/dev/null
  echo "== refresh.count =="
  cat "$D/refresh.count" 2>/dev/null
} > "$D/diag.txt" 2>&1
eips "diag done" 2>/dev/null
