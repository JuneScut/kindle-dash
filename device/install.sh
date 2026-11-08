#!/bin/sh
# 在 Mac 上跑：把 device/ 部署到已挂载的 Kindle。
#
#   sh device/install.sh
#
# 会自动探测本机局域网 IP 写进 config.sh，所以通常不用手改任何东西。

set -e

HERE=$(cd "$(dirname "$0")" && pwd)
KINDLE="${KINDLE:-/Volumes/Kindle}"
PORT="${PORT:-8000}"

if [ ! -d "$KINDLE" ]; then
    echo "找不到 $KINDLE"
    echo "先插上 Kindle，确认已经挂载（Finder 里能看到它）再跑一次。"
    exit 1
fi

IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)
if [ -z "$IP" ]; then
    echo "取不到本机 IP，请手动改 config.sh 里的地址"
    exit 1
fi

mkdir -p "$KINDLE/kindle-todo"
cp "$HERE/refresh.sh" "$HERE/loop.sh" "$KINDLE/kindle-todo/"
sed "s|192.168.0.100|$IP|" "$HERE/config.sh" > "$KINDLE/kindle-todo/config.sh"
# INTERVAL=60 sh device/install.sh  可以在部署时直接覆盖刷新间隔
if [ -n "$INTERVAL" ]; then
    sed -i '' "s|KINDLE_TODO_INTERVAL:-[0-9]*|KINDLE_TODO_INTERVAL:-$INTERVAL|" \
        "$KINDLE/kindle-todo/config.sh" 2>/dev/null \
        || sed -i "s|KINDLE_TODO_INTERVAL:-[0-9]*|KINDLE_TODO_INTERVAL:-$INTERVAL|" \
        "$KINDLE/kindle-todo/config.sh"
fi

# 书库里的"书"：点一下启动看板
cp "$HERE/start.sh" "$KINDLE/documents/dash-start.sh"

# 清掉之前实验留下的入口，避免书库里出现两个长得差不多的"书"
rm -f "$KINDLE/documents/dash-start-gui.sh" "$KINDLE/documents/jb-eips.sh" \
      "$KINDLE/documents/jb-diag.sh" "$KINDLE/documents/jb-test.sh" 2>/dev/null

echo "已部署到 $KINDLE"
echo "  服务地址: http://$IP:$PORT"
echo
echo "接着："
echo "  1. 本机跑  python3 serve.py"
echo "  2. 弹出 Kindle，去书库点『dash-start』"
