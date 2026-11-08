# 唯一需要改的地方：Mac 的局域网地址。
# 也可以不改这里，在 scriptlet 里 export KINDLE_TODO_BASE 覆盖。

KINDLE_TODO_BASE="${KINDLE_TODO_BASE:-http://192.168.0.100:8000}"
KINDLE_TODO_INTERVAL="${KINDLE_TODO_INTERVAL:-900}"    # 刷新间隔（秒），900=15分钟
KINDLE_TODO_DIR="/mnt/us/kindle-todo"                  # 设备上的工作目录
