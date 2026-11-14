# kindle-dash

把 Kindle Paperwhite 4（1072×1448）变成一块待办屏。

架构是"哑终端"：**电脑渲染整屏图，屏幕只负责显示这张图**。改版式 = 改 Python，设备端一辈子不用动。

```
Nasdaq 财报、Newsquawk 宏观日历、滴答清单
        │
        ▼
serve.py + render.py（VPS 或 Mac，Pillow） ──► 1072×1448 的黑白 PNG
        │ Kindle 发起 HTTP 请求，服务端按需渲染
        ▼
Kindle：wget + eips       ──►  画到墨水屏
```

```
kindle-dash/
├─ render.py          排版 + 渲染
├─ serve.py           HTTP 服务，按各数据源的计划自动同步
├─ fetch_market.py    抓 Nasdaq 财报日历（零 key）
├─ fetch_macro.py     抓 Newsquawk 宏观日历（零 key）
├─ data/board.json    看板快照，财报宏观和待办可以独立更新
├─ data/macro.json    宏观事件（自动生成，也可手改）
├─ data/company_cn.json  代码 → 中文名
├─ out/today.png      渲染产物
└─ device/
   ├─ config.sh       唯一需要改的地方（服务器地址、刷新间隔）
   ├─ refresh.sh      拉一次图 + 写屏
   ├─ loop.sh         定时循环
   ├─ start.sh        书库里的"书"，点一下启动
   └─ install.sh      Mac 上一键部署到 Kindle
```

---

## 1. 本机先跑通

```bash
python3 serve.py
```

会打印 `http://<你的IP>:8000/screen`。

- `/screen` 包了 `meta refresh`，浏览器里打开能自动刷新（适合越狱前先看版式）
- `/today.png` 单张整屏图
- `/todos.json` 原始数据
- `/draw.txt` 布局指令流（调试用）

没有 `data/board.json` 时可以用 `todos.md` 预览。每次图片请求都用本地快照重新渲染，不会访问数据源。

## 2. 部署到 Kindle

设备已越狱的前提下，**一条命令**：

```bash
sh device/install.sh
```

它会自动探测 Mac 的局域网 IP 写进 `config.sh`，然后把脚本推到 `/mnt/us/kindle-todo/`，并在书库里放一本叫 **dash-start** 的"书"。

然后：

1. 弹出 Kindle
2. 回书库，点开 **dash-start**
3. 屏幕刷出待办看板

> 书库里没看到 dash-start：等几秒让它索引，或者切换筛选器到「全部 / 文档」。

**不需要 KUAL，不需要 SSH。** 越狱后 `documents/` 里的 `.sh` 文件会自动变成可点的"书"，点一下就以 root 执行（官方叫 scriptlet）。

## 3. 部署到 VPS（推荐）

放在 Mac 上跑有三个单点故障：Mac 要醒着、代理要活着、局域网 IP 不能变。搬到一台常开的 VPS 上全没了。

### 3.1 环境

```bash
sudo apt install python3-pil python3-requests fonts-noto-cjk
```

> **中文字体是必须的**。Debian 默认一个 CJK 字体都没有，不装的话屏幕上全是豆腐块。
> `render.py` 会优先找 `/usr/share/fonts/opentype/noto/NotoSansCJK-*.ttc` 的 index 2（简体中文）。

### 3.2 代码与密钥

```bash
sudo git clone <你的仓库> /opt/kindle-dash
sudo chown -R $USER:$USER /opt/kindle-dash
```

密钥**不进 git**，单独传：

```bash
scp data/ticktick_client.json data/ticktick_token.json vps:/opt/kindle-dash/data/
ssh vps 'chmod 600 /opt/kindle-dash/data/ticktick_*.json'
```

### 3.3 systemd

```ini
# /etc/systemd/system/kindle-dash.service
[Unit]
Description=Kindle 墨水屏看板渲染服务
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=<your-user>
WorkingDirectory=/opt/kindle-dash
ExecStart=/usr/bin/python3 -u serve.py --host 127.0.0.1 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now kindle-dash
```

注意 `--host 127.0.0.1`：服务不直接暴露，由 nginx 反代。

### 3.4 nginx 反代（带口令的路径）

不想新开端口，就挂在已有的 80 端口站点里加一个 **随机路径**：

```nginx
location /kd-<你的随机串>/ {
    proxy_pass http://127.0.0.1:8000/;
    add_header Cache-Control "no-store" always;
}
```

> ⚠️ **随机串就是口令，绝对不要提交到仓库。** 路径公开等于看板公开 —— 上面有你的待办标题。

Kindle 端最终访问：

```
http://<vps-ip>/kd-<随机串>/page/0.png
```

### 3.5 为什么用 HTTP 不用 HTTPS

老 Kindle 的 TLS 栈验不过现代证书链（PW4 上踩过），而且 busybox `wget` 对 TLS 支持很差。看板内容只是待办标题，用 HTTP + 随机路径是够的。

## 4. 数据源

### 美股大事件（自动）

`fetch_market.py` 从 [Nasdaq 财报日历](https://api.nasdaq.com/api/calendar/earnings) 拉未来 7 天的财报 —— **零 API key**，每天几百家公司，接口里带市值字段。

```bash
python3 fetch_market.py                  # 默认：市值 ≥ 800 亿美元，每天 2 家，整屏 8 条
python3 fetch_market.py --days 10 --min-cap 50 --per-day 1
```

筛选逻辑：

1. 按市值排序，只留市值达标或在 `WATCHLIST` 里的（NVDA/AAPL/MSFT/… 见脚本顶部）
2. 同一家公司去重（BRK.A / BRK.B 只留一条）
3. 每天最多 `--per-day` 条
4. 整屏放不下就按市值砍到 `--max-rows`，再按日期排回来
5. 市值 ≥ 5000 亿美元的直接在屏上**反白**（黑底白字），一眼就能扫到

`serve.py` 按北京时间调度：

- **美股大事（Mac 和 VPS）**：每天 08:00 同步，范围为当天起连续 7 个自然日。财报每天重抓，宏观日历使用覆盖这 7 天、已经发布的周报。若只想每周更新一次，可用 `--market-refresh weekly`。
- **滴答清单**：每天 08:00 同步。
- 若错过同步时间，服务恢复后补跑；已经同步过的不会因重启重抓。失败时保留上次看板数据，每 30 分钟重试失败项。

`python3 serve.py --refresh-now` 可立即同步一次；`--no-fetch` 可关闭自动同步。Kindle 默认仍每 10 分钟拉图并轮播，每页页脚显示该数据源最近一次成功同步的日期和时间。

### 数据契约

`data/board.json` 是稳定层，渲染只认它：

```json
{
  "market_updated": "2026-11-02T08:00:00+08:00",
  "todo_updated": "2026-11-03T08:00:00+08:00",
  "market": [
    {"date": "11-02", "symbol": "AAPL", "title": "Apple",
     "when": "盘后", "cap": 5092, "hot": true}
  ],
  "family": []
}
```

- `date` 写 `MM-DD`，渲染时自动变「周一 / 今天」
- `symbol` 为空时，`title` 会当成整行标题显示（留给宏观事件用）
- `family` 非空时，屏幕自动切成上下两区；为空就美股独占整屏

### 宏观事件（也是零 key）

`fetch_macro.py` 抓 [Newsquawk 的 Week in Focus](https://www.newsquawk.com/daily/week-in-focus)。页面里带一段 JSON-LD，正文是 `MON: ... TUE: ...` 这种干净结构，直接正则就能拆，**不需要注册任何账号**。

```bash
python3 fetch_macro.py             # 抓最近一期，写 data/macro.json
python3 fetch_macro.py --dry-run   # 先看结果
```

只挑会动美股的（`PRIORITY` 表在脚本顶部，可按喜好调权重）：中期选举、FOMC、非农、CPI、PCE、ISM、GDP、零售销售… 每天最多两条，分数 ≥ 60 才显示。

**为什么不用 FRED / firecrawl**：FRED 要注册（且得用 Create New Account，不是 Sign In）；firecrawl 未登录且搜索返回散文、要 LLM 抽取、按次计费 —— 都不适合无人值守的定时任务。

> 兜底：如果新版周报未发布或无法识别，每天模式仍更新财报，并使用窗口内可用的宏观数据；每周模式保留上一份看板并重试。

## 5. 手势操作

看板运行时，触摸屏是可用的：

| 手势 | 行为 |
|---|---|
| **点击** | 退出看板，原生阅读界面回来，可以继续看书 |
| **左滑** | 下一页 |
| **右滑** | 上一页 |

> 退出时会看到和开机一样的亚马逊小树启动画面，约 20~30 秒。**那不是重启** —— 是 `lab126_gui` 在重新加载，书和阅读进度都不受影响。

### 触摸设备

```
event0  20cc000.snvs:snvs-powerkey   电源键
event1  bd71827-power                充电
event2  goodix-ts                    ← 触摸屏
```

这颗 Goodix 用 **MT 协议 B**，**没有 `BTN_TOUCH`**：

```
ABS_MT_TRACKING_ID >= 0   手指按下
ABS_MT_POSITION_X / _Y    移动（像素值，X 0~1071，Y 0~1447）
ABS_MT_TRACKING_ID == -1  抬起
ABS_MT_TOUCH_MAJOR        接触面积
```

### 在 shell 里读 evdev 的三个坑

这三个都真实踩过，每个都会让功能"完全不动"，而且不报错。

**① `od` 输出到管道是全缓冲**

`od /dev/input/event2 | awk ...` 会攒满 4KB（约 85 条事件）才输出。一次点击只有 6~7 条，事件永远卡在缓冲区里。

**② `$10` 不是第十个参数**

```sh
set -- $hex
type=$(( 0x$10$9 ))     # ✗ 这是 ${1} 接字面量 "0"
type=$(( 0x${10}${9} )) # ✓
```

**③ close() 会丢弃未读的事件**

evdev 在关闭 fd 时会清空该客户端的队列。所以不能"每次 `dd` 读一条就退出"—— 那样每条都会丢掉后面的事件，**抬起事件必然丢失**，手势永远判不出来。

```sh
exec 3< "$DEV"                     # 只打开一次
while :; do
    HEX=$(dd bs=16 count=1 <&3 2>/dev/null | od -An -tx1)
done
```

### 手势判定

```sh
有坐标 + 位移 ≥ 60px  → 滑动（按主轴定方向）
有坐标 + 位移 < 60px  → 点击
没有坐标              → 点击（快速轻点时驱动不给坐标，一定不是滑动）
```

调试时：`export TOUCH_DEBUG=1` 再跑 `touch-watch.sh`，会逐条记录事件和心跳，日志在 `/mnt/us/kindle-todo/touch.log`。

## 6. 越狱记录（这台设备的实际路径）

| 项 | 值 |
|---|---|
| 机型 | Kindle Paperwhite 4（2018），1072×1448 / 300ppi |
| 固件 | **5.16.3** |
| 方法 | **SpiderCat**（2026-09-01 发布）—— 侧载一本 `.azw3`，从书库打开即触发 |
| 结果 | `jb.sh v2.5.0`，`documents/JAILBROKEN.txt` 为证 |
| 附带 | `/mnt/us/libkh/bin/fbink` 已就位 |

### 为什么是 SpiderCat

它的入口是**电子书**，不走 Kindle 书店、不需要浏览器访问境外域名、可以 USB 侧载 —— 绕开了国区书店停服带来的所有不确定性。

```bash
# 步骤回顾
# 1. 填满磁盘防 OTA（FAT32 单文件上限 4GiB，要分多个文件写）
# 2. curl -L -o spidercat.azw3 https://kindlemodding.org/spidercat/spidercat.azw3
# 3. 放进 /Volumes/Kindle/documents/
# 4. 弹出，连 Wi-Fi，书库里打开它
# 5. 文字刷出 executing → 自动重启 → 越狱完成
```

### 踩过的坑

1. **`executing` 不代表成功**。azw3 里的 exploit 在执行 `curl` 之后立刻打印这三个字，不检查结果。停在这一行多半是网络没通，不是方法不对。
2. **`jb.sh` 不用手动放**。它是越狱内部组件（`jb.sh v2.5.0`），根目录放 `jb.sh` / `jb.so` 是别的越狱方法的做法，对 SpiderCat 无效。
3. **FAT32 时间戳没有时区**。macOS 按 UTC 显示，和北京时间差 8 小时。看到 `10月30 17:27` 其实是 `10月31 01:27`，别据此判断"谁动过设备"。
4. **填盘要留余量**，但别贴太死（留 ~50MB）。满盘 FAT32 上写临时文件会失败且不报错，表现为"脚本在跑但屏不动"。

### 已经被废弃的东西

- **KUAL**：官方明说 *obsolete and does not work*，别装了。用 scriptlet。
- **USBNetwork / SSH**：这套方案不需要，`dash-start` 点一下就行。

---

## 7. 耗电与上墙

| 方式 | 大致续航 |
|---|---|
| 30 分钟刷一次 + Wi-Fi 常开（默认） | 一两天，**建议一直插电** |
| `KEEP_GUI=0`（停掉原生界面独占屏幕） | 更省，但触屏失效，只能重启恢复 |

PW4 带前光，晚上要开灯才看得见，开灯就是持续耗电；挂有环境光的地方最省。

### 为什么不做"设备端按数据渲染"

按实际数字算过，不划算：

1. 整屏 PNG 只有 10~40 KB，30 分钟一张，一天不到 2 MB
2. 设备端只有 busybox `sh`，`eips` 只能整屏贴图，画不了矩形和线；中文要自带字体
3. 30 分钟闪一次无所谓，局部刷新的收益只在秒级刷新时存在

`render.py --drawlist` 保留了"布局 → 指令"的能力当调试工具，真要做块级增量也是从它长出来。

---

## 8. 参考

- [op7418/ai-desk-card](https://github.com/op7418/ai-desk-card) —— 这套哑终端架构的源头
- [dietrichmax/dashink](https://github.com/dietrichmax/dashink) —— Flask + Pillow 的 Kindle 版实现
- [kindlemodding.org](https://kindlemodding.org/) —— 越狱 wizard 与方法文档
- [SpiderCat](https://kindlemodding.org/jailbreaking/SpiderCat/) · [Installing Homebrew](https://kindlemodding.org/jailbreaking/whats-next/installing-homebrew.html) · [Hotfix](https://kindlemodding.org/kindle-hacking/hotfix.html)
