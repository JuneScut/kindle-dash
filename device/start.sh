#!/bin/sh
# 书库里的那本"书"。点一下 = 以 root 启动后台刷新循环。
#
# 注意：启动后会停掉原生界面（触屏失效），否则框架会把画面盖掉。
# 想恢复：长按电源 20 秒重启。

DIR=/mnt/us/kindle-todo

# 独占屏幕：停掉原生界面，否则框架重绘会把画面顶掉。
# 代价是触屏失效，恢复靠长按电源 20 秒。
# （保留界面的模式试过，框架一重绘就盖掉画面，已放弃，别再用。）
KEEP_GUI=0
export KEEP_GUI

# 先确认服务器真的可达。拉不到就别停原生界面，
# 否则屏幕会变成一块白板（框架退出时清屏，又没有新图填回去）。
if ! "$DIR/refresh.sh" --fetch-only; then
    echo "$(date '+%F %T') 服务器不可达，保留原生界面" >> "$DIR/refresh.log"
    exit 1
fi

pkill -f "$DIR/loop.sh" 2>/dev/null
pkill -f "$DIR/touch-watch.sh" 2>/dev/null
sleep 1

# setsid 让它脱离当前进程组：随后停 GUI 时不会被一起收掉
if command -v setsid >/dev/null 2>&1; then
    setsid "$DIR/loop.sh" >/dev/null 2>&1 &
    setsid "$DIR/touch-watch.sh" >/dev/null 2>&1 &
else
    nohup "$DIR/loop.sh" >/dev/null 2>&1 &
    nohup "$DIR/touch-watch.sh" >/dev/null 2>&1 &
fi
