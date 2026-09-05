# 桌面调试与后台操作

本地开发默认开放 Electron 原生 CDP 调试端口，不自动打开 DevTools 面板，不抢焦点。
操作顺序固定为：**现有 API → Playwright/CDP → 必要时桌面 UI**。可以后台完成的检查、读取和操作，不使用鼠标键盘打断用户。

## 开启范围

- Unpackaged Electron 启动默认开启；项目 Launcher 的本地启动、重建和 packaged 刷新均携带 `--local-debugging`，本机打包产物也开启。
- 对外分发的 packaged 程序直接启动时默认关闭；发行入口不得附带 `--local-debugging`。显式附带该参数视为本地调试启动。
- 地址固定为 `127.0.0.1`，端口由操作系统分配，禁止改成 `0.0.0.0`、固定猜测 `9222` 或加入 `--remote-allow-origins=*`。
- CDP 可操作当前登录页面，本机进程可连接；不得公开转发调试端口。
- 一个共享 DesktopShell 管理 Launcher、main 工作台和分支窗口，共用一个端口。二次启动只转发指令，不能覆盖主进程的调试发现文件。

## 发现地址

从项目根执行（Python 使用项目已验证的运行时）：

```powershell
.\.venv\Scripts\python.exe scripts\desktop_debug.py --project "<project-root>"
```

工具输出 `httpEndpoint`、`webSocketDebuggerUrl`、进程身份和实时 `targets`。传入已登记的 worktree 时自动解析其共享桌面壳。它只读，不启动或重启产品。

地址来自 Chromium 在 userData 中生成的 `DevToolsActivePort`，Electron 发布至 canonical runtime 的 `launcher/desktop_debug.json`。发现工具核对现有 shell owner 的 PID、创建时间、可执行文件、工作区和实时 browser WebSocket 地址；旧文件或端口被复用会明确失败，不能当成已连接。

## Playwright 后台连接与窗口识别

使用现有 Playwright 运行时；不额外启动浏览器，也不调用 `bringToFront()`：

```javascript
const browser = await chromium.connectOverCDP(discovery.webSocketDebuggerUrl);
try {
  const windows = [];
  for (const context of browser.contexts()) {
    for (const page of context.pages()) {
      const summary = await page.evaluate(async () =>
        window.vibelutionLauncher
          ? await window.vibelutionLauncher.getDesktopShellSummary()
          : null);
      windows.push({ page, url: page.url(), window: summary?.currentWindow });
    }
  }
  const main = windows.find(item => item.window?.role === 'main-workbench');
  if (!main) throw new Error('Main Workbench is not open');
  const version = await main.page.evaluate(() => window.vibelutionLauncher.getVersion());
  console.log({ url: main.url, version });
} finally {
  // connectOverCDP 的远程连接调用 close() 仅断开客户端；不发送 CDP Browser.close。
  await browser.close();
}
```

`currentWindow.role` 为 `launcher`、`main-workbench`、`branch-workbench` 或 `unknown`；分支返回 `instanceId`。按角色、实例和 URL 选择目标，不能用 `pages()[0]` 或仅凭标题判断。导航/重启后重新读取；`unknown` 不能猜成 main。

`getVersion()` 是桌面版本，不证明运行中代码和前端产物最新。构建验收仍需比对实际 Electron 进程、backend health 中的代码身份及前端 serving build 标识。

## 重启与重新连接

普通运行时刷新继续使用官方 Launcher：

```powershell
& "$env:LOCALAPPDATA\Vibelution\Launcher\VibelutionLauncher.exe" --project "<project-root>" restart
```

该命令成功不代表常驻 Electron 壳已经更换。首次给旧壳启用调试端口必须完整退出旧壳再启动；端口不能事后注入旧进程。

已有可信 unpackaged 主壳时，Launcher 的 main `start/restart/rebuild-and-start` 只转发指令，构建和受保护重启由常驻壳判断。入口不得提前编译并消耗 `rebuilt` 信号，否则会出现磁盘产物更新但旧壳未退出。

已有 CDP 时，完整退出通过可信页面已有的 `window.vibelutionLauncher.requestDesktopShellExit()`，等待实际退出，再由官方 Launcher `start` 启动。页面可能先断开导致 evaluate 抛错，必须检查进程退出结果，不能凭该异常判定失败或重复退出。不得发送 `Browser.close`、强杀或绕过 active-work guard。存在进行中的工作或 guard 无法确认时停止刷新并报告。

每次完整重启后重新运行发现命令、创建新的 `connectOverCDP` 连接，并重新识别页面。不得复用旧端口、WebSocket 地址或 Page 句柄。仅后台重连不会打开 DevTools 或激活窗口；产品正常启动是否显示工作台由既有 Launcher 行为决定。

## 验收

先在隔离的 `show:false` Electron 中验证只监听 loopback、读取页面、断开客户端后壳仍存活、退出后重新启动并重新发现端口。再验证实际产品的窗口角色和版本、守卫允许的完整退出及重新连接；磁盘编译成功或 backend restart 成功不能替代实际壳更新证据。

实现复用 Electron 原生 [remote-debugging-port](https://www.electronjs.org/docs/latest/api/command-line-switches#--remote-debugging-portport) 与 Playwright [connectOverCDP](https://playwright.dev/docs/api/class-browsertype#browser-type-connect-over-cdp)，进程身份和生命周期继续由项目现有 owner/Launcher 管理。
