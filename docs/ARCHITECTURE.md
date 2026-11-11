# 架构

Windows 专用。非 Windows 只能跑测试、`--demo` 和界面，不能碰真实显示器。

```text
控制台 (web/)                CLI brightness_vcp.py
        |                         |
        v                         v
FastAPI 127.0.0.1:8765      displayctl.cli
        \                       /
         v                     v
        displayctl.service.DisplayService
          身份、分类、确认、限速、回读、回滚
                     |
         +-----------+------------+
         |                        |
  dxva2_win (Windows)      memory (仅 --demo / 测试)
  EnumDisplayMonitors      不加载 dxva2
  VCP 0x10 / 0x12 / 0x62 读写（后两者同样要确认）
  能力字符串（按 EDID 缓存；只解析型号、10、12）
  注册表 EDID
```

## 分层

| 层 | 模块 | 职责 |
| --- | --- | --- |
| 入口 | `brightness_vcp.py`、`displayctl/cli.py`、`displayctl/api.py`、`displayctl/dev.py` | 命令行、本机 HTTP，以及一条命令同时起 API 和 Vite。不自己调用 `SetVCPFeature` |
| 安全服务 | `service.py`、`assemble.py`、`rate_limit.py`、`policy.py` | 唯一写入管线：`enumerate` / `probe` / `get_luminance` / `set_luminance_safe` |
| 身份 | `identity.py` | EDID 解析、型号解析、句柄匹配 |
| 后端 | `dxva2_win.py`、`backend.py`、`memory.py` | 打开句柄、读、关句柄；或内存假设备 |
| 界面 | `web/` | 控制台。滑块只改待写入值，按钮才发送 `confirm: true`。桌面布局只读，按 `rect` 画相对位置 |

`set_luminance_safe` 的确认参数是关键字参数，默认 `False`。调用方必须写成 `confirm=True`。

## 一次安全写入

```text
UI 按钮 / CLI --yes
        |
        v
confirm 与取值检查（失败则不探测）
        |
        v
重新 probe：枚举物理屏，读 EDID，重新读 0x10。能力字符串能用缓存就用缓存；0x10 已经失败则不再读能力字符串
        |
        v
组装身份。冲突、内屏、DDC/线缆/刻度不对 → 返回，写入 0 次
        |
        v
限速通过后，按 EDID 或几何重新找到恰好一个句柄
        |
        v
SetVCPFeature(..., <允许的 VCP>, value) 一次
        |
        v
等待并回读，最多两次
        |-- 一致 → 成功
        |-- 读不到 → 停止
        \-- 不一致 → 把原值写回去一次，再读，然后停止
```

列表读数有一层软缓存 `PROBE_CACHE_S`（8 秒），从这次探测**返回**时开始计，避免一次要数秒的枚举还没结束缓存就已经过期。界面大约每 5 秒刷新一次，安静时往往直接命中。写入、`probe()` 和 `get_luminance` 传 `fresh=True`，不用这层缓存。

同时进来的列表请求（`/api/monitors`、`enumerate_monitors`、`_load(fresh=False)`）共用同一次在途探测，不会在锁后面再排一串完整 DDC。

能力字符串另按 EDID 身份缓存 `CAPS_CACHE_S`（5 分钟）。冷列表优先只做 `EnumDisplayMonitors`、注册表 EDID 和 `GetVCP 0x10`；命中就不再调用 `CapabilitiesRequestAndCapabilitiesReply`。未命中才读一次并记下。有序列号的 EDID 用和身份相同的稳定 id；没有序列号时再绑上输出和几何，避免两台无序号面板共用一份字符串。没有可用 EDID 时不缓存，因为 `\\.\DISPLAYn` 会被系统复用。`0x10` 已经失败（内屏、DDC 不通）时直接跳过能力字符串，不再为一次读不到的请求花掉几百毫秒到数秒。若这个身份上缓存里还有字符串，失败的这次仍用它来判断对比度有没有声明，但不会因此去写。

同一台机器上的物理屏 DDC 仍然串行。不并行 `GetVCP` 或能力字符串。共享的 I²C/DDC 总线并行容易读坏。硬件锁包住整段写入：重新探测、一次 `SetVCPFeature`、回读、必要时回滚一次，不会和另一笔写入或另一趟探测交错。

## 句柄

`dxva2_win` 沿用原来的 CLI 调用顺序：

1. `EnumDisplayMonitors`
2. `GetNumberOfPhysicalMonitorsFromHMONITOR` / `GetPhysicalMonitorsFromHMONITOR`
3. 需要读数时先 `GetVCPFeatureAndVCPFeatureReply`（`0x10`）。`0x10` 成功且 caps 缓存未命中时读能力字符串；若声明了已知安全只读码或 caps 过稀，再串行 GetVCP（本版对比度 `0x12`、音量 `0x62`、RGB 增益 `0x16`/`0x18`/`0x1A`、输入源 `0x60`、电源 `0xD6`）
4. `DestroyPhysicalMonitors`

写入路径会再枚举一次以拿到新句柄，但不再为了匹配去读第二遍能力字符串。匹配用的是刚探测到的 EDID 或几何。`DestroyPhysicalMonitors` 失败也不会被当成“要再写一次”的信号。

EDID 来自注册表，不是另一个 VCP 读。`EnumDisplayDevicesW` 的 `DeviceID`（`MONITOR\AOCB433\{4d36e96e-…}\0003`）对应 `HKLM\SYSTEM\CurrentControlSet\Enum\DISPLAY\<id>\<实例>\Device Parameters\EDID`。同一 id 下会留下过期实例；只接受 `HardwareID` 含 `MONITOR\<id>`、且 `Driver` 与 DeviceID 里的类实例一致的块。多个实例都对上但 EDID 不同，或对上的那份块校验失败时，当作没有 EDID，避免两块屏共用一份能力字符串缓存。类键 `Control\Class\{…}\NNNN\Device Parameters\EDID` 只在没有任何一个实例对上时再试。`DeviceKey` 只有 128 个宽字符，截断或键不存在（有的机器上这个 `Device Parameters` 根本没有）就不当作一份可靠的块，不去猜。

## HTTP

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/health` | 平台、后端名、是否 demo、允许的 VCP 和限速。不探测显示器 |
| GET | `/api/monitors` | 列表，可带缓存 |
| GET | `/api/monitors/{id}` | 单台，强制重新探测 |
| GET | `/api/monitors/{id}/luminance` | 只读亮度；探测失败就是错误 |
| POST | `/api/monitors/{id}/luminance` | `{ "value": 0..100, "confirm": true }` |

每台显示器多一个 `capabilities`。`luminance` 来自这次已经做过的 `0x10` 读取，以及安全管线是否允许写。`contrast` / `volume` / `rgb_gains` / `input_source` / `power_mode` = 能力字符串声明 ∪ 对应 GetVCP 成功：无 vcp 段且无成功读数时为 `null`；声明或读数任一成立则给出对象。读数成功时 `readable` 为 true 并带当前值。亮度、对比度、音量在安全管线允许时可以 `writable: true`；RGB、输入源、电源保持只读。`rgb_gains` 含 `red`/`green`/`blue` 三通道。完整 VCP 码表不返回。`policy.vcp` 列出允许写入的 `0x10` / `0x12` / `0x62`。

静态文件：如果存在 `web/dist`，API 会在 `/` 提供构建好的控制台。`/api/*` 仍然走接口。

开发时运行 `python -m displayctl.dev`：API 固定 `127.0.0.1:8765`，Vite 优先 `127.0.0.1:5173`（占用则顺延并打印实际地址）。开发页把 `/api` 发给 Vite，再代理到 `http://127.0.0.1:8765`，所以不用手工对齐两个端口。构建后的页面由 API 同源提供。CORS 仍只放行固定的本机 Vite 源。

## 控制台

桌面布局是控制面。每块矩形用 `rect` 摆放（可以为负），上面是短名称和当前亮度。`capabilities.luminance.writable` 为真才在矩形里放滑块；滑块不写硬件，点「应用」才走原来的 `confirm: true`。不可写的矩形是虚线，只带一个短原因。对比度、音量在可写时使用和亮度相同的滑块，点「应用」并确认后才写入。RGB、输入源、电源在可读时显示只读徽章，不能写入。

选中一块屏时，布局下面有一行说明：待写入的差值、对比度/音量/RGB 只读信息，或这一次写入的结果。提示语只在标题下出现一次。

几何计算在 `displayctl/geometry.py`，界面公式在 `web/src/layout.ts`。`--demo` 把几台屏的能力分开：一台可写且声明了对比度/音量/RGB，一台只有亮度，其余没有 DDC。

服务离线时是未连接状态。「查看界面演示」不会发请求。`--demo` 的写入只改本进程里的假数据。

`/api/health` 的客户端时限仍是 8 秒（`HEALTH_TIMEOUT_MS`），因为它不碰 DDC。列表和亮度是 30 秒（`MONITORS_TIMEOUT_MS`、`LUMINANCE_TIMEOUT_MS`，见 `web/src/probeClient.ts`）。多屏 Windows 上，能力字符串还没缓存时，每台外接屏仍要付一次能力字符串读取（实测一台大约 2–4 秒），第一次冷列表因此还可能要数秒。EDID 能从 `Enum\DISPLAY` 解析出来之后，这份字符串按身份记下；8 秒列表软缓存过期后的下一次列表不再重读 caps，主要是枚举、EDID 和每台屏一次 `GetVCP 0x10`，预期大约 0.5–1 秒，而不是再走一趟约 5 秒的能力字符串。内屏因为 `0x10` 失败会跳过能力字符串。以前列表和健康检查共用 8 秒，硬刷新会在服务端还在探测时被浏览器取消，抛出的又不是 `ApiError`，界面就把正文写成「探测失败」。时限只影响等待，不改变确认、单次写入、回读和回滚。

同一次页面里重叠的 `GET /api/monitors` 合成一个在途请求。服务端也对列表探测做了 singleflight，所以开发模式的 `StrictMode` 双次挂载不会再把两趟完整 DDC 串成队。取消前一个 fetch 停不掉已经开始的枚举，所以卸载只作废那一代界面更新，不另外再开一趟 DDC。健康检查已经成功、但列表超时或连接中断时，界面说明是超时，并自动再要一次列表。写入失败仍只用服务返回的 `message`，不会自动再写。`--demo` 的探测几乎立即返回，不走这条慢路径。

主题是 `data-theme`：`night`（默认）、`graphite`、`day`。颜色都走 CSS 变量，切换时不改结构。

## 为什么序号不是主键

`EnumDisplayMonitors` 的顺序会随插拔和主屏变化。旧 CLI 的 `index` 保留给坐在机器前、刚执行过 `list` 的人做一次选择；真正落笔之前已经换成 id，并且在打开句柄时再对一次 EDID。API 从一开始就只收 id。
