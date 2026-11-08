#!/bin/sh
# 常驻监听触摸屏：
#   点击     → 退出看板，把原生阅读界面还回来
#   左右滑动 → 手动翻页
#
# 为什么不用 `od /dev/input/event2 | awk`：
#   od 输出到管道时是全缓冲（4KB≈85 条事件），一次点击只有 6~7 条，
#   事件会一直卡在缓冲区里出不来。所以改成每次 dd 读 16 字节，
#   正好是一条 Linux input_event，读完立刻解析。

. "$(dirname "$0")/config.sh"
DIR="$KINDLE_TODO_DIR"
DEV="${TOUCH_DEV:-/dev/input/event2}"
SWIPE_MIN=60          # 位移超过它算滑动，否则算点击

[ -e "$DEV" ] || exit 1
log() { echo "$(date '+%F %T') $*" >> "$DIR/touch.log"; }

restore_gui() {
    log "  cvm 进程: $(pidof cvm 2>/dev/null || echo 无)"

    # 框架启动时看到的是一块被我们画过的 framebuffer，先清干净
    eips -c 2>/dev/null
    sleep 1

    log "  start lab126_gui"
    start lab126_gui >> "$DIR/touch.log" 2>&1
    log "    rc=$?"

    # 给足 60 秒。每 10 秒记一次进程状态，看它是在启动还是彻底没动
    i=0
    while [ "$i" -lt 60 ]; do
        if pidof cvm >/dev/null 2>&1; then
            log "  cvm 已起来（${i}s）pid=$(pidof cvm)"
            return 0
        fi
        if [ $((i % 10)) -eq 0 ] && [ "$i" -gt 0 ]; then
            log "  ${i}s 时的相关进程: $(ps 2>/dev/null | grep -E 'cvm|lab126|framework' | grep -v grep | awk '{print $NF}' | tr '\n' ' ')"
        fi
        sleep 1
        i=$((i + 1))
    done

    log "  cvm 60 秒内未起来"
    return 1
}

log "watcher 启动 (设备 $DEV) pid=$$"

# 心跳：证明进程还活着（主循环会阻塞在 dd 上，等不到事件就什么都不写）
# 调试开关：默认关。排查时 export TOUCH_DEBUG=1 才有逐条事件和心跳
DEBUG="${TOUCH_DEBUG:-0}"
n=0
HEART=""

if [ "$DEBUG" = "1" ]; then
    ( while :; do
          sleep 30
          echo "$(date '+%F %T') beat" >> "$DIR/touch.log"
      done ) &
    HEART=$!
fi

# 日志别无限长
[ -f "$DIR/touch.log" ] && [ "$(wc -c < "$DIR/touch.log")" -gt 200000 ] && : > "$DIR/touch.log"

down=0; x0=0; y0=0; x1=0; y1=0

# 关键：把设备 fd 一直开着。
# evdev 在 close() 时会丢弃该客户端未读走的事件，
# 所以不能每次 dd 都重新打开 —— 那样每次只能拿到第一条，抬起事件必丢。
exec 3< "$DEV"

while :; do
    HEX=$(dd bs=16 count=1 <&3 2>/dev/null | od -An -tx1)
    if [ -z "$HEX" ]; then
        [ "$DEBUG" = "1" ] && log "dd 返回空"
        sleep 1
        continue
    fi

    set -- $HEX
    [ $# -lt 16 ] && continue

    # 注意：$10 会被当成 ${1}0，必须写成 ${10}
    type=$(( 0x${10}${9} ))
    [ "$type" -ne 3 ] && continue              # 只处理 EV_ABS
    code=$(( 0x${12}${11} ))
    val=$(( 0x${16}${15}${14}${13} ))
    [ "$val" -ge 2147483648 ] && val=$(( val - 4294967296 ))

    n=$((n + 1))
    [ "$DEBUG" = "1" ] && [ "$n" -le 100 ] && log "  ev#$n type=$type code=$code val=$val"

    case "$code" in
        57)  # ABS_MT_TRACKING_ID：按下 / 抬起
            if [ "$val" -ge 0 ]; then
                down=1; x0=-1; y0=-1; x1=-1; y1=-1
            elif [ "$down" = "1" ]; then
                down=0
                if [ "$x0" -lt 0 ] || [ "$x1" -lt 0 ]; then
                    # 快速轻点时驱动只报按下/抬起，不给坐标。
                    # 没有坐标就不可能是滑动，直接当点击。
                    ax=0; ay=0; dx=0; dy=0
                else
                    dx=$(( x1 - x0 )); dy=$(( y1 - y0 ))
                    ax=${dx#-}; ay=${dy#-}
                fi
                if [ "$ax" -ge "$SWIPE_MIN" ] || [ "$ay" -ge "$SWIPE_MIN" ]; then
                    if [ "$ax" -ge "$ay" ]; then
                        [ "$dx" -lt 0 ] && act=SWIPE_LEFT || act=SWIPE_RIGHT
                    else
                        [ "$dy" -lt 0 ] && act=SWIPE_UP || act=SWIPE_DOWN
                    fi
                else
                    act=TAP
                fi

                case "$act" in
                    TAP)
                        log "tap -> 退出看板 (dx=$dx dy=$dy)"
                        pkill -f "$DIR/loop.sh" 2>/dev/null
                        lipc-set-prop com.lab126.powerd preventScreenSaver 0 2>/dev/null
                        restore_gui
                        log "恢复流程结束"
                        [ -n "$HEART" ] && kill "$HEART" 2>/dev/null
                        exit 0
                        ;;
                    SWIPE_LEFT|SWIPE_RIGHT)
                        read -r cur total < "$DIR/page-state" 2>/dev/null
                        if [ -n "$total" ] && [ "$total" -gt 1 ]; then
                            if [ "$act" = "SWIPE_LEFT" ]; then
                                target=$(( (cur + 1) % total ))
                            else
                                target=$(( (cur - 1 + total) % total ))
                            fi
                            log "$act -> 第 $target 页 (dx=$dx)"
                            echo "$target" > "$DIR/pending-page"
                            "$DIR/refresh.sh" &
                        else
                            log "$act 但只有 1 页，忽略"
                        fi
                        ;;
                esac
            fi
            ;;
        53) [ "$down" = "1" ] && { [ "$x0" -lt 0 ] && x0=$val; x1=$val; } ;;   # X
        54) [ "$down" = "1" ] && { [ "$y0" -lt 0 ] && y0=$val; y1=$val; } ;;   # Y
    esac
done
