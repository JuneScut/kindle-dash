# 解析 /dev/input/eventN 的 od -An -v -tx1 输出，识别一次手势后打印并退出。
#   TAP / SWIPE_LEFT / SWIPE_RIGHT / SWIPE_UP / SWIPE_DOWN
#
# 输入是每行 16 字节（正好一条 Linux input_event）：
#   timeval(4+4) | type(2) | code(2) | value(4)   全部小端

function hex(h,   i, c, v, d) {
    d = "0123456789abcdef"
    v = 0
    for (i = 1; i <= length(h); i++) {
        c = tolower(substr(h, i, 1))
        v = v * 16 + index(d, c) - 1
    }
    return v
}

{
    if (NF < 16) next
    type = hex($10 $9)
    if (type != 3) next                 # 只关心 EV_ABS
    code = hex($12 $11)
    v = hex($16 $15 $14 $13)
    if (v >= 2147483648) v -= 4294967296

    if (code == 57) {                   # ABS_MT_TRACKING_ID
        if (v >= 0) {                   # 手指按下
            down = 1; x0 = -1; y0 = -1; x1 = -1; y1 = -1
        } else if (down) {              # 手指抬起，判定手势
            down = 0
            if (x0 < 0 || x1 < 0) next
            dx = x1 - x0
            dy = y1 - y0
            ax = (dx < 0 ? -dx : dx)
            ay = (dy < 0 ? -dy : dy)
            if (ax >= 80 || ay >= 80) {
                if (ax >= ay) print (dx < 0 ? "SWIPE_LEFT" : "SWIPE_RIGHT")
                else          print (dy < 0 ? "SWIPE_UP" : "SWIPE_DOWN")
                exit
            } else if (ax <= 25 && ay <= 25) {
                print "TAP"
                exit
            }
        }
    } else if (code == 53 && down) {    # ABS_MT_POSITION_X
        if (x0 < 0) x0 = v
        x1 = v
    } else if (code == 54 && down) {    # ABS_MT_POSITION_Y
        if (y0 < 0) y0 = v
        y1 = v
    }
}
