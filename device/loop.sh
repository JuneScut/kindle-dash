#!/bin/sh
# 定时刷新循环。
#
# 默认 KEEP_GUI=0：必须停掉原生界面。
# 不停的话，scriptlet 一退出、阅读器关书回书库，框架立刻重绘，把我们的图盖掉。
# 代价是触屏失效，想恢复就长按电源 20 秒重启。

. "$(dirname "$0")/config.sh"

KEEP_GUI="${KEEP_GUI:-0}"

if [ "$KEEP_GUI" = "1" ]; then
    lipc-set-prop com.lab126.powerd preventScreenSaver 1 2>/dev/null
    # 等书关掉、书库重绘完再画第一帧，否则会被立刻覆盖
    sleep 8
else
    lipc-set-prop com.lab126.powerd preventScreenSaver 1 2>/dev/null
    stop lab126_gui 2>/dev/null \
        || /etc/init.d/framework stop 2>/dev/null \
        || killall lab126_gui 2>/dev/null
    sleep 3
fi

while true; do
    # 每轮都重新读一次配置：改了间隔不用重启循环，下一轮自动生效
    . "$(dirname "$0")/config.sh"

    # 服务端可以远程指定间隔（/interval.txt），改参数不用插 USB。
    # 低于 30 秒的一律忽略，避免误配把屏刷爆。
    REMOTE=$(wget -q -O - "$KINDLE_TODO_BASE/interval.txt" 2>/dev/null)
    case "$REMOTE" in
        ''|*[!0-9]*) : ;;
        *) [ "$REMOTE" -ge 30 ] && KINDLE_TODO_INTERVAL="$REMOTE" ;;
    esac

    "$(dirname "$0")/refresh.sh"
    sleep "$KINDLE_TODO_INTERVAL"
done
