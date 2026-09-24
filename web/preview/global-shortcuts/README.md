# 全局快捷键 × 命令面板 · 隔离预览

任务级临时预览（分支 `codex/zcode-global-shortcuts-palette`），演示借鉴 zai-org/ZCode
（Apache-2.0）`packages/ui/src/shortcuts` 体系模式、本仓库 TS 自研的全局快捷键基建，
并把 `web/src` 的真实 `VCommandPalette` / `VSessionSearchDialog`（mock 数据）用全局快捷键唤起。

**不进生产路由 / 不改 web/src 任何文件 / 不新增依赖。**

## 启动

```bash
# 在 worktree 的 web/ 下（或仓库任意位置，路径指向本目录的 vite 配置）
cd <worktree>/web
npx vite --config preview/global-shortcuts/vite.config.ts
```

- 端口：**5196**（strictPort；host 127.0.0.1）
- URL：`http://127.0.0.1:5196/preview/global-shortcuts/index.html`
- 根路径 `/` 会 302 到预览页。
- 无需后端：全部为 mock 数据与演示动作，无生产接口调用。

## 演示内容

1. **快捷键注册表基建**（`src/shortcuts/`）：
   - `bindingFormat.ts` — canonical 绑定串（`CmdOrCtrl+k` 形式）解析/序列化 + event.code 反查表；
   - `platform.ts` — CmdOrCtrl 平台分解、mac/Win 标签、冲突检测用物理等价归一（canonical key）；
   - `commands.ts` — 命令表 + 生效表计算（默认绑定 / 用户覆盖整组替换 / 显式空数组=清除不回退 / 非法条目忽略）；
   - `conflicts.ts` — 保留键黑名单 + 占用检测（canonical 键比较）；
   - `useGlobalShortcuts.ts` — window capture 分发 + IME/长按噪声过滤 + 精确修饰键匹配 + 录制器。
2. **真实组件挂载**：`Ctrl+K` 唤起 VCommandPalette、`Ctrl+P` 唤起 VSessionSearchDialog
   （mac 上为 ⌘K / ⌘P；页面按宿主平台匹配，展示标签可切「模拟 macOS」）。
3. **关键状态**：面板打开/空态、搜索打开/过滤高亮/空态、占用冲突拒绝提示、
   保留键拒绝、录制新绑定、显式空数组清除（「未设置」）、操作日志空态。

## 确定性初始态（URL 参数，截图与分享用）

| state 参数 | 场景 |
| --- | --- |
| （无） | 桌面主视口默认态 |
| `palette` | 命令面板打开 |
| `palette-empty` | 命令面板空态（预置零命中查询） |
| `search` | 会话搜索打开（全部结果 + 加载更多） |
| `search-filtered` | 搜索过滤命中 + 关键词高亮 |
| `search-empty` | 会话搜索空态 |
| `conflict` | 占用冲突拒绝提示（Ctrl+K 绑到会话搜索） |
| `recording` | 录制新绑定态（openCommandPalette） |
| `cleared` | 显式空数组清除（切密度 → 未设置） |

另有 `?theme=dark|light` 控制主题。

## 截图

```bash
node preview/global-shortcuts/scripts/capture-screens.mjs
```

输出到 `preview/global-shortcuts/screenshots/`（依赖本机 Chrome headless；可用
`GSP_CHROME` / `GSP_BASE_URL` 环境变量覆盖浏览器路径与服务地址）。

## 类型检查与自检

本目录有自己的 tsconfig（只含 `src`，引用真实 web/src 组件一并参与类型检查）：

```bash
npx tsc -p preview/global-shortcuts/tsconfig.json
```

纯逻辑自检（匹配/录制/生效表/冲突检测 33 项断言，esbuild 打包后 node 执行）：

```bash
node preview/global-shortcuts/scripts/logic-selftest.mjs
```

浏览器分发链路自检：打开
`http://127.0.0.1:5196/preview/global-shortcuts/index.html?selftest=1`，
页面会合成一次 Ctrl+K 走真实 window capture 分发链路，并在 `<html>` 上写
`data-selftest-hotkey="palette-open"`（失败为 `fail`）。

生产门 `npx tsc -b --pretty false`（web/）不受影响：预览目录不在其 include 内。

## 与 ZCode 的有意差异

- `CmdOrCtrl+p` 用作会话搜索默认键（VS Code 惯例、需求指定）；ZCode 因浏览器打印
  保留键将其拉黑。预览页对命中的按键 preventDefault 接管，集成阶段需再裁决产品语义。
- AltGr 语义、mac 菜单通道（channel: "menu"）不在预览范围。
