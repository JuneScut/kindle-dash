#!/bin/sh
# 探测触摸设备：抓 40 秒原始事件，用来判断"点击"和"滑动"的特征。
#
# 重要：scriptlet 的 stdout 会当成"书"的内容显示，所以这里把输出全部丢弃，
# 否则 eips 自己那行 "swipe feature is not supported" 会盖住屏上提示。
# 点开之后**立刻**开始滑动和点击，不用等提示。

exec >/dev/null 2>&1

D=/mnt/us/kindle-todo
OUT="$D/input-probe"
mkdir -p "$OUT"

cp /proc/bus/input/devices "$OUT/devices.txt"
ls -l /dev/input/ > "$OUT/nodes.txt"
echo "start $(date)" > "$OUT/meta.txt"

# 每个输入节点各开一个后台抓取
for dev in /dev/input/event*; do
    [ -e "$dev" ] || continue
    name=$(basename "$dev")
    ( od -An -v -tx1 "$dev" 2>/dev/null | head -n 4000 > "$OUT/$name.hex" ) &
    eval "PID_$name=\$!"
done

sleep 40

for dev in /dev/input/event*; do
    [ -e "$dev" ] || continue
    name=$(basename "$dev")
    eval "p=\$PID_$name"
    [ -n "$p" ] && kill "$p" 2>/dev/null
done

echo "end $(date)" >> "$OUT/meta.txt"
ls -l "$OUT" >> "$OUT/meta.txt"
