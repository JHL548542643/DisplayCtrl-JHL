# DisplayCtl

Windows 本地应用：通过 DDC/CI（MCCS）控制外接显示器的亮度、对比度和音量。提供系统托盘和原生窗口，标题栏颜色跟随「夜航 / 石墨 / 日间」主题。

应用名是 **DisplayCtl**，本仓库是 [JHL548542643/DisplayCtrl-JHL](https://github.com/JHL548542643/DisplayCtrl-JHL)。

## 下载预览版

到 [Releases](https://github.com/JHL548542643/DisplayCtrl-JHL/releases) 下载 `DisplayCtl.exe`。当前预览版标签为 `v0.3.1-preview`。

- 双击运行会打开原生窗口；关掉窗口后程序仍在托盘里，可再次打开或退出。
- 端口优先使用 `8765`，被占用时自动向上寻找空闲端口。
- 亮度、对比度、音量可以拖动，点「应用」并确认后才写入显示器。
- RGB 增益、输入源、电源状态目前是只读徽章。
- 本工具只监听本机回环地址（`127.0.0.1`）。没有 Linux / macOS 后端，也不会改笔记本内屏亮度。
- 预览版 exe 尚未签名，个别杀毒软件可能误报，这是 PyInstaller 单文件的常见情况。
- 启动失败时，可在 exe 同目录查看 `displayctl-preview.log`。

也可以在命令行运行：

```text
DisplayCtl.exe
DisplayCtl.exe --demo
DisplayCtl.exe --port 8877 --no-browser
```

`--demo` 使用内存里的假显示器，不调用 dxva2。

## 安全模型（摘要）

写入走同一条管线：重新探测 → 明确确认 → 只写一次允许的 VCP → 回读 → 不一致则把原值写回去一次。

当前允许写入的码（均限制在 `0..100`）：

- 亮度 `0x10`
- 对比度 `0x12`
- 音量 `0x62`

RGB、输入源、电源以及其它 VCP 不会被写入。身份优先用 EDID，分不清就不写。详见 [docs/SAFETY.md](docs/SAFETY.md)。

## 从源码开发

需要 Python 3.11+，控制台还需要 Node.js 22。

```powershell
python -m pip install -e ".[dev]"
cd web
npm install
cd ..
python -m displayctl.dev
```

开发页把 `/api` 代理到 `http://127.0.0.1:8765`。若 8765 已经是 DisplayCtl，会继续使用现有进程。

演示后端：

```powershell
python -m displayctl.dev --demo
```

命令行：

```powershell
python -m displayctl list
python -m displayctl set <index> <0-100> --yes
```

`set` 没有 `--yes` 会拒绝。`index` 只在这一次 `list` 里有效；真正写入前会换成稳定身份。

## 本地打包

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

产物是 `release\DisplayCtl.exe`。`release/` 已被 git 忽略，请不要把本机打包结果提交进仓库。GitHub Release 中的 exe 由 Actions 构建。

## GitHub Release

推送匹配 `v*` 的标签时，GitHub Actions 会在 `windows-latest` 上构建，并把 `DisplayCtl.exe` 挂到对应 Release。名称含 `preview` / `rc` / `alpha` / `beta` 的标签会标成预发布。工作流只使用 `GITHUB_TOKEN`，不需要额外密钥。

## 许可证

MIT License。见 [LICENSE](LICENSE)。
