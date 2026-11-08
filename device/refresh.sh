#!/bin/sh
# 拉一张整屏图，写到墨水屏。
#
# 这台机器（PW4 / 5.16.3）实测：
#   eips -g <png> -f      → 可用，update_mode=FULL
#   fbink -g <png>        → 参数非法，必须 -g file=<png> 或 -i <png>
# 所以优先 eips，fbink 用正确语法作备选。

. "$(dirname "$0")/config.sh"

# 上次自动发现的地址优先（Mac 的 IP 会变，变一次屏就死一次）
[ -s "$KINDLE_TODO_DIR/base-current" ] && KINDLE_TODO_BASE=$(cat "$KINDLE_TODO_DIR/base-current")

# 配置里的地址不通时，扫一遍同网段找服务
find_base() {
    prefix=$(echo "$KINDLE_TODO_BASE" | sed 's|^http://||; s|\.[0-9]*:[0-9]*$||')
    port=$(echo "$KINDLE_TODO_BASE" | sed 's|.*:||')
    i=100
    while [ "$i" -le 120 ]; do
        cand="http://$prefix.$i:$port"
        if wget -q -T 2 -O /dev/null "$cand/pages.txt" 2>/dev/null; then
            echo "$cand" > "$KINDLE_TODO_DIR/base-current"
            echo "$cand"
            return 0
        fi
        i=$((i + 1))
    done
    return 1
}

NEW="$KINDLE_TODO_DIR/dash.new"
CUR="$KINDLE_TODO_DIR/dash.png"
CNT="$KINDLE_TODO_DIR/refresh.count"
LOG="$KINDLE_TODO_DIR/refresh.log"

# --fetch-only：只把图拉下来，不碰屏幕（用于"先确认服务器活着"）
FETCH_ONLY=0
[ "$1" = "--fetch-only" ] && FETCH_ONLY=1

mkdir -p "$KINDLE_TODO_DIR" 2>/dev/null

# 轮播：问服务端一共几页，按刷新次数取模决定这一屏放哪页
PAGES=$(wget -q -T 3 -O - "$KINDLE_TODO_BASE/pages.txt" 2>/dev/null)
case "$PAGES" in
    ''|*[!0-9]*) PAGES=1 ;;
esac
[ "$PAGES" -lt 1 ] && PAGES=1
N=$(cat "$CNT" 2>/dev/null || echo 0)
PAGE=$(( N % PAGES ))

# 滑动翻页会写 pending-page 指定这一屏放哪页
FORCED=$(cat "$KINDLE_TODO_DIR/pending-page" 2>/dev/null)
case "$FORCED" in
    ''|*[!0-9]*) : ;;
    *) [ "$FORCED" -lt "$PAGES" ] && PAGE=$FORCED && rm -f "$KINDLE_TODO_DIR/pending-page" ;;
esac

echo "$PAGE $PAGES" > "$KINDLE_TODO_DIR/page-state"

if ! wget -q -T 5 -O "$NEW" "$KINDLE_TODO_BASE/page/$PAGE.png"; then
    # 先试着自动找一下服务，找不到才放弃
    if NEWBASE=$(find_base); then
        echo "$(date '+%F %T') 地址变了，自动切到 $NEWBASE" >> "$LOG"
        KINDLE_TODO_BASE="$NEWBASE"
        if ! wget -q -T 5 -O "$NEW" "$KINDLE_TODO_BASE/page/$PAGE.png"; then
            echo "$(date '+%F %T') 切过去还是拉取失败" >> "$LOG"
            exit 1
        fi
    else
        echo "$(date '+%F %T') 拉取失败，同网段也没找到服务" >> "$LOG"
        exit 1
    fi
fi
if [ ! -s "$NEW" ]; then
    rm -f "$NEW"
    echo "$(date '+%F %T') 空文件，保留上一屏" >> "$LOG"
    exit 1
fi
mv "$NEW" "$CUR"

[ "$FETCH_ONLY" = "1" ] && exit 0

n=$(( $(cat "$CNT" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$CNT"

# 主路径：eips（已验证可用）
if eips -g "$CUR" -f 2>>"$LOG"; then
    exit 0
fi
echo "$(date '+%F %T') eips 失败，试 fbink" >> "$LOG"

# 备选：fbink，注意是 -i <file> 或者 -g file=<file>
FBINK=""
for c in /mnt/us/libkh/bin/fbink /mnt/us/koreader/fbink; do
    [ -x "$c" ] && FBINK="$c" && break
done
if [ -n "$FBINK" ]; then
    "$FBINK" -q -i "$CUR" -f 2>>"$LOG" && exit 0
fi

echo "$(date '+%F %T') 两种方式都失败" >> "$LOG"
exit 1
