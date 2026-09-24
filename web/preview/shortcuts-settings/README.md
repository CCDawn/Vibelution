# 快捷键设置面板 · 隔离预览

任务级临时预览（分支 `codex/zcode-shortcuts-settings-preview`）：为「全局快捷键改键设置面」做的
设置页 UI 预览，复刻设置页（`ConfigSettingsIndex`）的视觉语言。**不进生产路由 / 不改 `web/src`
任何文件 / 不新增依赖**；交互核心只读 import `web/src/shortcuts` 的真实纯逻辑。

## 启动

```bash
# 方式一：从仓库 worktree 的 web/ 下（推荐；node_modules 用 junction 指向根，无需安装）
cd <worktree>/web
npx vite --config preview/shortcuts-settings/vite.config.ts

# 方式二：从本目录
cd <worktree>/web/preview/shortcuts-settings
npm run dev

# 截图 + 交互自检（自行拉起/关闭 dev server，需本机 python playwright）
cd <worktree>/web/preview/shortcuts-settings
python scripts/capture_screens.py
```

- 端口：**5198**（strictPort；host 127.0.0.1）
- URL：`http://127.0.0.1:5198/preview/shortcuts-settings/index.html`
- 根路径 `/` 会 302 到预览页；无需后端，无生产接口调用。
- 覆盖持久化走真实 localStorage 键 `vibelution.shortcuts.overrides`（预览页自身 origin 内生效，
  与生产 origin 隔离）。

## 演示内容

1. **命令清单行**：命令名 + 说明 + 当前绑定（kbd 呈现，平台标签 Ctrl / ⌘ 可切）+
   「修改」「清除」操作；覆盖状态徽章（默认 / 已覆盖 / 已清除）。
2. **修改 = 录制态**：捕获下一个按键组合；纯修饰键给出 pending 提示；Esc 取消；
   无修饰的普通字符键拒绝；保留键（如 Enter）拒绝并提示。
3. **占用冲突**：录制到其他命令已占用的组合时拒绝，横幅给出占用方命令与
   `canonicalBindingKey` 物理归一判定详情（平台等价组合不漏检）。
4. **显式空数组 = 清除**：清除后行内显示「未设置」徽章且不回退默认；reload 后仍生效；
   「恢复默认」移除该命令的覆盖键。
5. **恢复全部默认**：底部一键清空全部覆盖并移除持久化键。

## 确定性初始态（URL 参数）

| state 参数 | 场景 |
| --- | --- |
| （无） | 设置清单默认态 |
| `recording` | 录制态（打开命令面板行） |
| `conflict` | 占用冲突拒绝（CmdOrCtrl+k → 会话搜索，被命令面板占用） |
| `reserved` | 保留键拒绝（Enter → 会话搜索） |
| `cleared` | 显式空数组清除（命令面板 → 未设置） |

另有 `?theme=dark|light` 控制主题。

## 截图

`scripts/capture_screens.py` 用真实交互（点击/按键）驱动 6 个场景截图并做断言，
输出到 `screenshots/` 并写 `capture-report.json`（含断言结果与 console/pageerror 收集，
任何 console error 都会让脚本失败）。

## 真实基建清单（只读 import）

- `web/src/shortcuts/commands.ts` — 命令表 + `resolveEffectiveBindings` 生效表
  （默认 / 整组替换 / 显式空数组=清除 / 非法条目忽略）；
- `web/src/shortcuts/bindingFormat.ts` — canonical 绑定串解析/序列化（经生效表间接使用）；
- `web/src/shortcuts/conflicts.ts` — `checkBindingConflict` 保留键黑名单 + 占用检测；
- `web/src/shortcuts/platform.ts` — `formatBindingLabel` 平台标签、`canonicalBindingKey`
  物理归一、`isAppleKeyboardPlatform` 宿主平台；
- `web/src/shortcuts/shortcutOverrides.ts` — 真实 localStorage 键的读/写/清洗；
- `web/src/shortcuts/useGlobalShortcuts.ts` — window capture 分发 + 录制器 hook；
- `web/src/components/vui` — `VButton` / `VChip` / `VuiProvider` 与设计令牌
  （`tokens.css` / `base.css` / `vui-provider-theme.css` / `vui-native-controls.css` /
  `theme.tailwind.css`），全部只读引用。

## 模拟项（集成时需裁决）

- 命令说明文案为本预览本地 map（真实命令表暂无 `description` 字段）；
- 「全局命令触发」只做演示横幅，无真实动作；
- 平台标签切换按钮（模拟 ⌘）仅影响展示，不影响匹配口径；
- 快捷键设置作为 settings section 的分组/导航归属未定（本页用「导航」组复刻设置页分组视觉）。

## 类型检查与边界

- 本目录有自己的 tsconfig（只含 `src`，真实 web/src 依赖一并参与类型检查）：
  `npx tsc -p preview/shortcuts-settings/tsconfig.json`
- 生产门 `npx tsc -b --pretty false`（web/）与生产 vitest include 均不含 `preview/`，
  预览不参与生产构建/测试。
- Tailwind 使用本预览自己的入口 `src/preview.tailwind.css`（生产 `tailwind.css` 的
  `@source` 不含 preview 目录）；主题 token 与生产同一份，本目录样式只用 vui 令牌类，
  无内置字号/裸 hex/任意圆角。
