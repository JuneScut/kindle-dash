#!/bin/sh
exec >/dev/null 2>&1
D=/mnt/us/kindle-todo
{
  echo "== stdbuf ==";   command -v stdbuf || echo 无
  echo "== timeout ==";  command -v timeout || echo 无
  echo "== evtest ==";   command -v evtest || echo 无
  echo "== hexdump ==";  command -v hexdump || echo 无
  echo "== busybox 版本 =="; busybox 2>&1 | head -1
  echo "== 相关 applet =="
  busybox --list 2>/dev/null | grep -E "^(stdbuf|timeout|hexdump|od|dd|awk|setsid)$"
} > "$D/tools.txt" 2>&1
