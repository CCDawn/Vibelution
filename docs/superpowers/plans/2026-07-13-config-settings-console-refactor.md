# 桌面设置控制台整体重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `/config` 重构为桌面端全高设置控制台，让用户通过一级分区和单一子页面快速找到、编辑并保存配置，同时修复 Provider 管理区行高过小和底部大面积空白。

**Architecture:** 保留 `ConfigRoute` 作为配置查询、草稿、保存和 Provider mutation 的唯一状态拥有者；新增纯展示的设置导航组件，显式建模“一级分区 → 本地子页面 → 底层配置分区”。页面外壳使用固定桌面侧栏、唯一全局状态/保存页头和 `minmax(0, 1fr)` 主工作区；普通配置、原始配置和模型连接复用现有 VUI/HeroUI 组合，不增加数据事实源。

**Tech Stack:** React 19、TypeScript 5.9、Vite 8、Vitest、Tailwind CSS v4、VUI、HeroUI、React Query。

## Global Constraints

- 正式配置源保持 `C:\Users\17533\Documents\Vibelution\config\config.toml`，不得新增配置副本或写入路径。
- 不修改后端 API、Provider draft、模型发现、推荐、路由替换或保存协议。
- 不做手机端、触屏端或窄屏响应式适配；验收视口固定为 1280×720、1600×900、1920×1080。
- 一级导航最小高度 44px；普通按钮、输入框和选择器 40–44px；紧凑次操作不低于 36px；Provider 行最小高度 58px。
- route 文件不得直接引入 `@heroui/react`；继续通过 `../components/vui` 使用组件。
- 不引入新依赖，不修改 `VERSION`、`CHANGELOG.md`、`web/package.json` 或 `web/package-lock.json`。
- 不记录凭据、配置全文、原始 Provider 响应或 secret；现有有界 mutation 日志保持不变。
- 根目录 `main` 只用于最终本地集成；开发继续在 `codex/config-settings-console-refactor` 工作树完成。

---

## 文件职责映射

### 新建

- `web/src/routes/ConfigSettingsNavigation.tsx`：设置一级分区、本地子页面模型、选择解析、侧栏和子页面标签渲染。
- `web/src/routes/ConfigSettingsNavigation.styles.ts`：44px 一级导航、40px 子页面标签、固定桌面侧栏和横向标签滚动样式。
- `web/src/routes/ConfigSettingsNavigation.test.tsx`：分区映射、Git 提交配置可达性、选择回退和服务端静态渲染契约。

### 修改

- `web/src/routes/ConfigRoute.tsx`：接入两级导航；移除可缩放/可收起侧栏；只渲染当前子页面；统一页头状态和操作；保持所有配置状态与 mutation ownership。
- `web/src/routes/ConfigRoute.styles.ts`：全高两栏外壳、唯一滚动容器、40–44px 控件、舒适表单密度和模型工作区高度传递。
- `web/src/routes/ConfigRoute.layout.test.ts`：新增整体结构契约并删除旧侧栏缩放、组内全量堆叠和重复操作断言。
- `web/ConfigRoute.layout.test.ts`：让根级内容体验契约跟随抽取后的设置导航定义。
- `web/src/routes/ConfigOverviewPanel.tsx` / `.styles.ts`：总览只显示模型、阻塞和警告摘要，不再重复配置路径、保存操作、环境变量入口或原始 TOML。
- `web/src/routes/ConfigDraftPanel.tsx` / `.styles.ts`：原始配置子页面同时承载结构化 JSON 编辑检查和当前外部 TOML 只读参考，并填满内容高度。
- `web/src/routes/ConfigWorkspacePlaceholderPanel.tsx` / `.styles.ts`：加载和错误占位匹配新的六分区、固定侧栏和全高主工作区。
- `web/src/routes/ConfigProviderRegistryPanel.tsx` / `.styles.ts`：全高 Provider rail/detail、58px Provider 行、填满高度的标签内容和固定底部危险区。
- `web/src/routes/ConfigProviderRegistryPanel.test.tsx`：补充 Provider 行、全高工作区、详情 body 和危险区契约；保留模型行为测试。
- `web/src/routes/ConfigQuickSetupPanel.tsx` / `.styles.ts`：在新主工作区内扩展可用宽度，统一 40px 输入和按钮；不改变状态机。
- `web/src/routes/ConfigQuickSetupPanel.test.tsx`：保留 input/checking/error/review/saving/success 行为并增加尺寸与反馈区域契约。

## 实施方案

### Task 1: 建立两级设置导航模型与纯展示组件

**Files:**
- Create: `web/src/routes/ConfigSettingsNavigation.tsx`
- Create: `web/src/routes/ConfigSettingsNavigation.styles.ts`
- Create: `web/src/routes/ConfigSettingsNavigation.test.tsx`
- Modify: `web/src/routes/ConfigRoute.layout.test.ts`

**Interfaces:**
- Consumes: `ConfigSummary["sections"]`、当前语言、现有一级分区标题/摘要。
- Produces:
  - `ConfigSettingsPage { id: string; title: string; summary: string; memberSectionIds: string[] }`
  - `ConfigSettingsGroup { id: string; title: string; summary: string; pages: ConfigSettingsPage[] }`
  - `buildConfigSettingsGroups(sections, groupCopy, language): ConfigSettingsGroup[]`
  - `resolveConfigSettingsSelection(groups, groupId, pageId): { group: ConfigSettingsGroup | null; page: ConfigSettingsPage | null }`
  - `ConfigSettingsSidebar` 和 `ConfigSettingsPageTabs`。

- [ ] **Step 1: 写失败的导航映射与渲染测试**

在 `ConfigSettingsNavigation.test.tsx` 使用 `renderToStaticMarkup`，明确断言：

```tsx
const groups = buildConfigSettingsGroups(sections, groupCopy, "zh");

expect(groups).toHaveLength(6);
expect(groups.find((group) => group.id === "tooling-diagnostics")?.pages).toEqual(
  expect.arrayContaining([
    expect.objectContaining({ id: "tooling-access", memberSectionIds: ["security", "network", "parser"] }),
    expect.objectContaining({ id: "tooling-logs", memberSectionIds: ["log", "debug"] }),
    expect.objectContaining({ id: "tooling-git", memberSectionIds: ["git-commit-model", "git-commit-prompt"] }),
    expect.objectContaining({ id: "tooling-health", memberSectionIds: ["health-diagnostics"] }),
    expect.objectContaining({ id: "tooling-raw", memberSectionIds: ["draft"] }),
  ]),
);

const selection = resolveConfigSettingsSelection(groups, "models-profiles", "missing");
expect(selection.group?.id).toBe("models-profiles");
expect(selection.page?.id).toBe("model-connection");
```

静态渲染还要断言六个一级按钮、当前 `aria-pressed`、本地标签 `aria-current="page"`，并确认组件源码没有 `@heroui/react`。

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
npm --prefix web test -- --run src/routes/ConfigSettingsNavigation.test.tsx
```

Expected: FAIL，错误指向 `ConfigSettingsNavigation` 模块不存在。

- [ ] **Step 3: 实现确定性的分区和页面定义**

在 `ConfigSettingsNavigation.tsx` 建立以下页面定义；只保留当前 workspace 中实际存在的 member section，页面为空时不渲染：

```ts
const PAGE_DEFINITIONS = {
  "overview-apply": [
    { id: "overview-status", zh: "状态总览", en: "Status", members: ["overview"] },
    { id: "overview-changes", zh: "变更与保存", en: "Changes", members: ["diagnostics"] },
  ],
  "workbench-interface": [
    { id: "workbench-behavior", zh: "工作台行为", en: "Workbench", members: ["shell"] },
    { id: "workbench-ui", zh: "界面显示", en: "Interface", members: ["ui"] },
  ],
  "avatar-pet": [
    { id: "identity-user", zh: "用户资料", en: "User profile", members: ["user-profile"] },
    { id: "identity-avatar", zh: "终端形象", en: "Avatar", members: ["avatar"] },
    { id: "identity-pet", zh: "陪伴体", en: "Companion", members: ["pet"] },
  ],
  "models-profiles": [
    { id: "model-connection", zh: "模型连接", en: "Connections", members: ["models"] },
    { id: "model-discovery", zh: "模型发现", en: "Discovery", members: ["llm-discovery"] },
  ],
  "runtime-context": [
    { id: "runtime-context", zh: "上下文压缩", en: "Context", members: ["context-compression"] },
    { id: "runtime-analysis", zh: "分析", en: "Analysis", members: ["analysis"] },
  ],
  "tooling-diagnostics": [
    { id: "tooling-access", zh: "工具与权限", en: "Tools & access", members: ["security", "network", "parser"] },
    { id: "tooling-logs", zh: "日志与调试", en: "Logs & debug", members: ["log", "debug"] },
    { id: "tooling-git", zh: "Git 提交", en: "Git commits", members: ["git-commit-model", "git-commit-prompt"] },
    { id: "tooling-health", zh: "健康诊断", en: "Health", members: ["health-diagnostics"] },
    { id: "tooling-raw", zh: "原始配置", en: "Raw config", members: ["draft"] },
  ],
} as const;
```

`buildConfigSettingsGroups` 必须以 `sections` 的 title/summary 作为单 section 页面的说明，并为组合页使用稳定的本地文案。`resolveConfigSettingsSelection` 的回退顺序固定为：请求 group → 第一个 group；请求 page → group 第一个 page。

- [ ] **Step 4: 实现侧栏和本地标签**

`ConfigSettingsSidebar` 只渲染页面身份、一个同步状态和六个一级按钮；`ConfigSettingsPageTabs` 只渲染当前 group 的页面：

```tsx
<nav className={styles.groupNav} aria-label={language === "zh" ? "设置分区" : "Settings groups"}>
  {groups.map((group) => (
    <VButton
      key={group.id}
      className={group.id === activeGroupId ? `${styles.groupButton} ${styles.groupButtonActive}` : styles.groupButton}
      aria-pressed={group.id === activeGroupId}
      onPress={() => onSelectGroup(group.id)}
    >
      <span>{group.title}</span>
    </VButton>
  ))}
</nav>
```

样式必须包含 `min-h-11` 一级按钮、`min-h-10` 本地标签、固定 `clamp(15.5rem, 17vw, 18rem)` 侧栏宽度和 `overflow-x-auto` 本地标签栏。

- [ ] **Step 5: 运行测试并确认通过**

Run:

```powershell
npm --prefix web test -- --run src/routes/ConfigSettingsNavigation.test.tsx src/routes/ConfigRoute.layout.test.ts
```

Expected: 新导航测试 PASS；旧 route 布局测试仍 PASS 或只在下一任务明确替换的旧侧栏断言处失败。

- [ ] **Step 6: 提交导航模型**

```powershell
git add -- web/src/routes/ConfigSettingsNavigation.tsx web/src/routes/ConfigSettingsNavigation.styles.ts web/src/routes/ConfigSettingsNavigation.test.tsx web/src/routes/ConfigRoute.layout.test.ts
git commit -m "feat(config): add settings navigation model"
```

### Task 2: 接入固定侧栏、唯一页头和单子页面渲染

**Files:**
- Modify: `web/src/routes/ConfigRoute.tsx`
- Modify: `web/src/routes/ConfigRoute.styles.ts`
- Modify: `web/src/routes/ConfigRoute.layout.test.ts`

**Interfaces:**
- Consumes: Task 1 的 `buildConfigSettingsGroups`、`resolveConfigSettingsSelection`、`ConfigSettingsSidebar`、`ConfigSettingsPageTabs`。
- Produces: `activeGroupId`、`activePageId` 和 `activePage.memberSectionIds`，供全部设置面板判断可见性。

- [ ] **Step 1: 写失败的 route 外壳契约测试**

在 `ConfigRoute.layout.test.ts` 新增断言：

```ts
expect(routeSource).toContain("const [activeGroupId, setActiveGroupId]");
expect(routeSource).toContain("const [activePageId, setActivePageId]");
expect(routeSource).toContain("<ConfigSettingsSidebar");
expect(routeSource).toContain("<ConfigSettingsPageTabs");
expect(routeSource).toContain("activePage?.memberSectionIds.includes(sectionId)");
expect(routeSource).not.toContain("SIDEBAR_WIDTH_STORAGE_KEY");
expect(routeSource).not.toContain("beginSidebarResize");
expect(routeSource).not.toContain("sidebarIndexCollapsed");
expect((routeSource.match(/<VRouteHeader\b/g) ?? []).length).toBe(1);
expect(routeSource).not.toContain("styles.sidebarMetaStrip");
expect(styles.page).toContain("[grid-template-rows:minmax(0,1fr)]");
expect(styles.content).toContain("[grid-template-rows:auto_auto_minmax(0,1fr)]");
```

同时把旧的侧栏缩放、收起索引、组内所有 section 同时可见断言删除。

- [ ] **Step 2: 运行测试确认新契约失败**

Run:

```powershell
npm --prefix web test -- --run src/routes/ConfigRoute.layout.test.ts
```

Expected: FAIL，错误集中在导航状态、旧 resize 代码和全高样式。

- [ ] **Step 3: 删除侧栏尺寸持久化和拖动逻辑**

从 `ConfigRoute.tsx` 删除 `SIDEBAR_*` 常量、`readStoredNumber`、`readStoredFlag`、clamp helpers、宽高 state、localStorage effects、window resize effect、`beginSidebarResize`、reset handlers、三个 resize handle 和 sidebar 折叠状态。页面不再生成 `pageStyle` 或 `sidebarStyle`。

- [ ] **Step 4: 建立 group/page 选择状态**

保持现有 `?section=models-profiles`、`?section=runtime-context` 深链接兼容；`section` 继续表示一级 group。实现：

```ts
const [activeGroupId, setActiveGroupId] = useState(() => searchParams.get("section") ?? "");
const [activePageId, setActivePageId] = useState("");
const settingsGroups = useMemo(
  () => buildConfigSettingsGroups(workspace?.sections ?? [], groupCopy, currentLanguage),
  [currentLanguage, groupCopy, workspace?.sections],
);
const { group: activeGroup, page: activePage } = useMemo(
  () => resolveConfigSettingsSelection(settingsGroups, activeGroupId, activePageId),
  [activeGroupId, activePageId, settingsGroups],
);
```

group 改变时同步选择该 group 第一页；page 改变时只滚动内容工作区顶部，不清空 `draftConfig`、`jsonText`、`providerQuickSetupState` 或 Provider 局部状态。

- [ ] **Step 5: 只渲染当前子页面**

把 `isSectionVisible` 改为：

```ts
function isSectionVisible(sectionId: string): boolean {
  return Boolean(activePage?.memberSectionIds.includes(sectionId));
}
```

`activeEditorSections` 只过滤 `activePage.memberSectionIds`。Provider 自动发现 effect 只在 `activeGroup.id === "models-profiles" && activePage.id === "model-connection"` 时运行，保持现有 sequential refresh 和错误处理。

- [ ] **Step 6: 重建唯一页头和内容网格**

页头保留当前 group 标题、同步状态、重新读取和保存；移除页头中的“打开系统环境变量”和“还原编辑文本”。配置路径放在状态详情的 `title`/可复制次级文本，不创建第二张路径卡。

内容结构固定为：

```tsx
<VSurface as="section" className={styles.content} padding="none">
  <div className={styles.configHeader}>...</div>
  <ConfigSettingsPageTabs ... />
  <div ref={contentViewportRef} className={styles.pageViewport}>
    {notice.text ? <div className={...}>{notice.text}</div> : null}
    {renderedActivePage}
  </div>
</VSurface>
```

`styles.page` 使用两栏和 `height:100%`；`styles.content` 使用 `grid-template-rows:auto auto minmax(0,1fr)`；`styles.pageViewport` 是默认唯一纵向滚动容器。

- [ ] **Step 7: 运行导航和 route 契约测试**

Run:

```powershell
npm --prefix web test -- --run src/routes/ConfigSettingsNavigation.test.tsx src/routes/ConfigRoute.layout.test.ts
```

Expected: PASS。

- [ ] **Step 8: 提交设置外壳**

```powershell
git add -- web/src/routes/ConfigRoute.tsx web/src/routes/ConfigRoute.styles.ts web/src/routes/ConfigRoute.layout.test.ts
git commit -m "refactor(config): build full-height settings shell"
```

### Task 3: 简化总览并把原始编辑器移入工具分区

**Files:**
- Modify: `web/src/routes/ConfigOverviewPanel.tsx`
- Modify: `web/src/routes/ConfigOverviewPanel.styles.ts`
- Modify: `web/src/routes/ConfigDraftPanel.tsx`
- Modify: `web/src/routes/ConfigDraftPanel.styles.ts`
- Modify: `web/src/routes/ConfigRoute.tsx`
- Modify: `web/src/routes/ConfigRoute.layout.test.ts`

**Interfaces:**
- `ConfigOverviewPanel` consumes `workspace.modelLibraryCount`、`workspace.blockingCount`、`workspace.warningCount`，不再接收 reload/environment/restore callbacks。
- `ConfigDraftPanel` 新增 `configPath: string` 和 `rawToml: string`，继续拥有 JSON 编辑器的检查/还原交互展示。

- [ ] **Step 1: 写失败的总览与原始配置契约**

在布局测试中断言：

```ts
expect(overviewPanelSource).toContain("workspace.modelLibraryCount");
expect(overviewPanelSource).toContain("workspace.blockingCount");
expect(overviewPanelSource).toContain("workspace.warningCount");
expect(overviewPanelSource).not.toContain("onOpenEnvironment");
expect(overviewPanelSource).not.toContain("workspace.rawToml");
expect(draftPanelSource).toContain("rawToml: string");
expect(draftPanelSource).toContain("configPath: string");
expect(draftPanelSource).toContain("<LazyJsonCodeMirror");
expect(draftPanelSource).toContain("<pre");
expect(routeSource).toContain('activePage?.id === "tooling-access"');
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
npm --prefix web test -- --run src/routes/ConfigRoute.layout.test.ts
```

Expected: FAIL，错误指向旧总览动作/raw TOML 和 DraftPanel props。

- [ ] **Step 3: 把总览改为决策摘要**

`ConfigOverviewPanel` 只渲染三个摘要卡：模型数量、阻塞问题、警告信号。状态值包含文字；阻塞/警告为 0 时使用成功/中性表达。删除配置路径、同步状态、重新读取、环境变量、还原文本和 raw TOML details，避免与全局页头重复。

- [ ] **Step 4: 把 JSON/TOML 合并到原始配置子页面**

`ConfigDraftPanel` 使用两层结构：上方 action rail（检查、还原、编辑同步提示），下方 `minmax(0, 1fr)` JSON 编辑器；“当前外部 config.toml”作为默认收起的只读 details，显示 `configPath` 和 `rawToml`，不能编辑 TOML，也不能创建第二个保存按钮。

- [ ] **Step 5: 在工具页恢复低频入口**

当 `activePage.id === "tooling-access"` 时，在结构化 editor sections 前渲染运行档位、默认模式、默认入口、进化审核和开发者模式的 `VStatusStrip`，并提供“打开系统环境变量”次操作。该入口只出现一次。

- [ ] **Step 6: 运行测试并提交**

Run:

```powershell
npm --prefix web test -- --run src/routes/ConfigRoute.layout.test.ts
```

Expected: PASS。

```powershell
git add -- web/src/routes/ConfigOverviewPanel.tsx web/src/routes/ConfigOverviewPanel.styles.ts web/src/routes/ConfigDraftPanel.tsx web/src/routes/ConfigDraftPanel.styles.ts web/src/routes/ConfigRoute.tsx web/src/routes/ConfigRoute.layout.test.ts
git commit -m "refactor(config): separate overview from raw config"
```

### Task 4: 统一桌面表单密度和加载占位

**Files:**
- Modify: `web/src/routes/ConfigRoute.styles.ts`
- Modify: `web/src/routes/ConfigWorkspacePlaceholderPanel.tsx`
- Modify: `web/src/routes/ConfigWorkspacePlaceholderPanel.styles.ts`
- Modify: `web/src/routes/ConfigRoute.layout.test.ts`

**Interfaces:**
- Consumes: 现有 `ConfigSectionEditor` DOM class names。
- Produces: route-local 40px control token、双列表单卡、44px 导航匹配的加载占位。

- [ ] **Step 1: 写失败的尺寸与占位契约**

新增断言：

```ts
expect(styles.page).toContain("[--control-height:40px]");
expect(styles.page).toContain("[--vui-control-height-sm:40px]");
expect(styles.field).toContain("[grid-template-columns:minmax(12rem,0.34fr)_minmax(0,1fr)]");
expect(styles.actionButton).toContain("[min-height:40px]");
expect(styles.primaryButton).toContain("[min-height:40px]");
expect(placeholderPanelSource).toContain("总览与保存");
expect(placeholderPanelSource).toContain("工具与诊断");
expect(placeholderPanelStyles.loadingNavList).toContain("[min-height:44px]");
expect(placeholderPanelStyles.loadingShell).toContain("[height:100%]");
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
npm --prefix web test -- --run src/routes/ConfigRoute.layout.test.ts
```

Expected: FAIL，错误指向 27–30px 控件和旧英文五项占位导航。

- [ ] **Step 3: 设置 route-local 控件尺寸**

在 `styles.page` 设置 `--control-height:40px` 和 `--vui-control-height-sm:40px`。`actionButton`、`primaryButton` 和危险按钮显式使用 `min-height:40px`；只有表格内 `density="compact"` 次操作允许 36px。

把 `field`、`treeFieldCardView`、`treeFieldCardEdit` 调整为桌面双列 label/control 布局；正文和字段值默认使用 `var(--vui-font-sm)`，`xs` 只保留眉题、元数据、badge 和非关键 hint。

- [ ] **Step 4: 统一区块节奏**

表单行使用 12–16px 间距，区块使用 20–24px 间距；删除仅为压缩内容而存在的 6–8px 主要表单 padding。保留 avatar、pet、context compression 等专用布局，不改变字段种类、值和保存方法。

- [ ] **Step 5: 更新加载和错误占位**

占位侧栏使用六个中文一级分区标签和 44px 行高；主区骨架使用页头、子页面标签、内容三行网格。错误 tone 只改变边界与状态，不改变布局尺寸。

- [ ] **Step 6: 运行测试并提交**

Run:

```powershell
npm --prefix web test -- --run src/routes/ConfigRoute.layout.test.ts
```

Expected: PASS。

```powershell
git add -- web/src/routes/ConfigRoute.styles.ts web/src/routes/ConfigWorkspacePlaceholderPanel.tsx web/src/routes/ConfigWorkspacePlaceholderPanel.styles.ts web/src/routes/ConfigRoute.layout.test.ts
git commit -m "style(config): normalize desktop settings density"
```

### Task 5: 让 Provider 管理真正填满工作区

**Files:**
- Modify: `web/src/routes/ConfigProviderRegistryPanel.tsx`
- Modify: `web/src/routes/ConfigProviderRegistryPanel.styles.ts`
- Modify: `web/src/routes/ConfigProviderRegistryPanel.test.tsx`
- Modify: `web/src/routes/ConfigRoute.styles.ts`

**Interfaces:**
- Consumes: 现有 `VSplitWorkspace`、Provider rows、selected tab 和 mutation callbacks。
- Produces: `detailBody`、`dangerZone` 两个明确布局区域；不改变 `ConfigProviderRegistryPanelProps` 行为签名。

- [ ] **Step 1: 写失败的 Provider 工作区测试**

替换旧 `max-h` 断言并增加：

```ts
expect(panelStyles.sectionSurface).toContain("h-full");
expect(panelStyles.registryWorkspace).toContain("[--vui-workspace-sidebar:clamp(22rem,28%,28rem)]");
expect(panelStyles.providerList).toContain("h-full");
expect(panelStyles.providerButton).toContain("!min-h-[58px]");
expect(panelStyles.detailSurface).toContain("[grid-template-rows:auto_auto_auto_minmax(0,1fr)_auto]");
expect(panelStyles.detailBody).toContain("min-h-0");
expect(panelStyles.tableScroll).toContain("h-full");
expect(panelStyles.tableScroll).not.toContain("max-h-[calc(100dvh-33rem)]");
expect(panelSource).toContain('data-provider-tab={selectedTab}');
expect(panelSource).toContain('data-provider-danger-zone="true"');
expect(panelSource).not.toContain("mobileActionGroup");
```

保留模型筛选、固定/取消固定、测试调用、空目录与反馈测试。

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
npm --prefix web test -- --run src/routes/ConfigProviderRegistryPanel.test.tsx
```

Expected: FAIL，错误指向 content-sized registry 和旧高度上限。

- [ ] **Step 3: 重排 Provider detail DOM**

在 tabs 后增加唯一内容容器，并把删除区移到底部：

```tsx
<div className={styles.detailBody} data-provider-tab={selectedTab}>
  {selectedTab === "connection" ? <ConnectionTab provider={provider} /> : null}
  {selectedTab === "models" ? <ProviderModelsTab {...modelProps} /> : null}
  {selectedTab === "protocols" ? <ProtocolsTab provider={provider} /> : null}
  {selectedTab === "diagnostics" ? <DiagnosticsTab provider={provider} disabled={disabled} onDiscover={onDiscover} /> : null}
</div>
<div className={styles.dangerZone} data-provider-danger-zone="true">
  <VButton variant="danger" ...>删除 Provider</VButton>
  {providerDeleteBlocked ? <p className={styles.critical}>...</p> : null}
</div>
```

反馈仍在 Provider header 与 tabs 之间，保持 `aria-live`。

- [ ] **Step 4: 实现全高样式**

`sectionSurface` 使用 `h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden`；`registryWorkspace` 使用 `h-full min-h-0` 和 `clamp(22rem,28%,28rem)`；rail/list/detail/body 全链路传递 `min-h-0`。Provider 行 58px、左右 12px padding、名称使用 `sm`、id 使用 `xs`。

模型 tab 使用 `grid-template-rows:auto minmax(0,1fr)`；`tableScroll` 使用 `h-full min-h-0 overflow-auto`，保留 sticky table header。连接、协议和诊断 tab 在 `detailBody` 内滚动并填满高度。

- [ ] **Step 5: 让 ConfigRoute 模型容器传递高度**

`providerModelsLayout` 和模型连接当前 mode 容器必须使用 `height:100%`、`min-height:0` 和 `grid-template-rows:auto minmax(0,1fr)`；Provider 编辑/preview surface 出现时作为覆盖或明确附加行，不把 registry 压缩成顶部窄条。

- [ ] **Step 6: 运行测试并提交**

Run:

```powershell
npm --prefix web test -- --run src/routes/ConfigProviderRegistryPanel.test.tsx src/routes/ConfigRoute.layout.test.ts
```

Expected: PASS。

```powershell
git add -- web/src/routes/ConfigProviderRegistryPanel.tsx web/src/routes/ConfigProviderRegistryPanel.styles.ts web/src/routes/ConfigProviderRegistryPanel.test.tsx web/src/routes/ConfigRoute.styles.ts
git commit -m "refactor(config): fill provider management workspace"
```

### Task 6: 对齐快速配置宽度和按钮状态

**Files:**
- Modify: `web/src/routes/ConfigQuickSetupPanel.tsx`
- Modify: `web/src/routes/ConfigQuickSetupPanel.styles.ts`
- Modify: `web/src/routes/ConfigQuickSetupPanel.test.tsx`
- Modify: `web/src/routes/ConfigRoute.tsx`
- Modify: `web/src/routes/ConfigRoute.styles.ts`

**Interfaces:**
- Consumes: 现有 `ProviderQuickSetupState` 和 callbacks。
- Produces: 相同状态机与数据行为，只改变主工作区宽度、控件尺寸和模式按钮反馈。

- [ ] **Step 1: 写失败的快速配置布局契约**

保留全部 13 个现有行为测试，并增加：

```ts
expect(styles.workspace).toContain("max-w-[88rem]");
expect(styles.field).toContain("[&_[data-vui=select-trigger]]:!min-h-10");
expect(styles.primaryAction).toContain("min-h-10");
expect(styles.reviewActions).toContain("items-end");
expect(panelSource).toContain('aria-live="polite"');
```

`ConfigRoute.layout.test.ts` 断言模型模式按钮使用统一 `styles.providerModeButton`，selected mode 仍通过 `variant="primary"` 和文本表达。

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
npm --prefix web test -- --run src/routes/ConfigQuickSetupPanel.test.tsx src/routes/ConfigRoute.layout.test.ts
```

Expected: FAIL，错误指向 72rem 上限和小尺寸 controls。

- [ ] **Step 3: 扩展桌面工作区但保持单流程**

把 quick setup 最大宽度调整为 88rem；Provider、API Key 和检测按钮保持同一行，字段最小高度 40px，主按钮宽度稳定。检测前继续不渲染结果面；checking/error/review/saving/success 继续在输入区下方渐进出现。

- [ ] **Step 4: 统一模型模式按钮**

“快速配置 / 管理已有连接 / 高级设置”三按钮使用 40px 高度、稳定 padding 和 `aria-pressed`；选中态不只依赖描边。模式标题和说明只保留一套，不在每个 mode 内重复。

- [ ] **Step 5: 运行测试并提交**

Run:

```powershell
npm --prefix web test -- --run src/routes/ConfigQuickSetupPanel.test.tsx src/routes/ConfigProviderRegistryPanel.test.tsx src/routes/ConfigRoute.layout.test.ts
```

Expected: PASS，至少 73 个设置相关测试通过，实际数量以新增测试为准且 0 failures。

```powershell
git add -- web/src/routes/ConfigQuickSetupPanel.tsx web/src/routes/ConfigQuickSetupPanel.styles.ts web/src/routes/ConfigQuickSetupPanel.test.tsx web/src/routes/ConfigRoute.tsx web/src/routes/ConfigRoute.styles.ts
git commit -m "style(config): align provider setup controls"
```

### Task 7: 完整验证、视觉修正和本地收尾

**Files:**
- Modify only if evidence requires: files already listed in Tasks 1–6。
- Update after local-main integration: `.docs/project-memory/lanes/web-workbench-surface.json` and generated project-memory outputs through the sync script only。

**Interfaces:**
- Consumes: Tasks 1–6 完整实现。
- Produces: 自动测试、构建、Launcher、浏览器、项目记忆和 claim release 的新鲜证据。

- [ ] **Step 1: 运行全部设置测试**

```powershell
npm --prefix web test -- --run src/routes/ConfigSettingsNavigation.test.tsx src/routes/ConfigRoute.layout.test.ts src/routes/ConfigProviderRegistryPanel.test.tsx src/routes/ConfigQuickSetupPanel.test.tsx
```

Expected: 全部 PASS，0 failures。

- [ ] **Step 2: 运行完整 Web 测试与构建**

```powershell
npm --prefix web test
npm --prefix web run build
```

Expected: Vitest 0 failures；TypeScript 和 Vite build exit 0。

- [ ] **Step 3: 运行本地 closeout gate**

若工作树缺少 `.venv`，先验证目标 `C:\Users\17533\Desktop\Vibelution\.venv` 后在任务工作树创建 junction；不得复制或修改 venv 内容。

```powershell
& ".\.venv\Scripts\python.exe" ".\scripts\local_quality_gate.py" closeout --base-ref main
```

Expected: 选中的 Web/Python 检查全部 PASS；VUI boundary 不出现 route 级 HeroUI import。

- [ ] **Step 4: 进行 diff 自审**

```powershell
git status --short --branch
git diff main...HEAD --check
git diff --stat main...HEAD
```

确认没有后端/API/config/version/package 变更，没有未跟踪截图或凭据，没有把其他 Agent 改动带入任务提交。

- [ ] **Step 5: 快进合入本地 main 并根目录复验**

先重新运行 guard `status/check`，确认 root `main` 干净且没有新重叠 claim；然后在根目录：

```powershell
git merge --ff-only codex/config-settings-console-refactor
npm --prefix web test -- --run src/routes/ConfigSettingsNavigation.test.tsx src/routes/ConfigRoute.layout.test.ts src/routes/ConfigProviderRegistryPanel.test.tsx src/routes/ConfigQuickSetupPanel.test.tsx
npm --prefix web run build
```

Expected: fast-forward 成功，根目录测试/build exit 0。

- [ ] **Step 6: 通过 Launcher 刷新运行时**

先检查 active work guard。若有活动任务，报告标准阻塞语句并停止刷新；若无活动任务：

```powershell
& ".\scripts\vibelution_launcher.ps1" -Action restart
```

Expected: frontend `http://127.0.0.1:8000` 与 workspace API 返回 200，运行时加载当前 `main` 构建。

- [ ] **Step 7: 真实浏览器视觉验收**

使用 in-app browser 打开 `/config`，每个视口都覆盖浅色和深色主题：

- 1280×720：六个一级导航、页头动作、本地标签不重叠；允许横向标签滚动但页面无横向溢出。
- 1600×900：普通表单双列对齐；总览无原始编辑器；工具页可达 Git 提交和原始配置。
- 1920×1080：Provider rail/detail 使用剩余高度；Provider 行至少 58px；模型表格填满内容区；危险区固定在详情底部。

至少验证 synced、dirty、quick setup checking/error/review/success、Provider connection/models/diagnostics。测量 `.pageViewport`、Provider rail/detail/table 的 clientHeight/scrollHeight，并保存必要截图证据。若出现遮挡、双永久纵向滚动条、底部大面积无意义空白或按钮小于规格，回到对应 Task 做最小修正并重跑相关测试/build。

- [ ] **Step 8: 同步项目记忆并释放 claim**

```powershell
& ".\.venv\Scripts\python.exe" "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\sync_project_memory.py" "C:\Users\17533\Desktop\Vibelution" --lane "web-workbench-surface" --focus "Desktop settings console refactor" --update "Refactored /config into fixed navigation, one active subpage, unified save status, comfortable controls, and a full-height Provider workspace; verified tests, build, Launcher, and desktop browser layouts."
```

检查 `.docs/project-memory/memory.json`、lane JSON、`overview.html` 和 `INDEX.md` 已出现最新记录，然后：

```powershell
& ".\.venv\Scripts\python.exe" "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py" "C:\Users\17533\Desktop\Vibelution" release --claim-id "claim-d4584ed61d84" --status completed --reason "设置控制台重构已合入本地 main，并完成测试、构建、Launcher、浏览器和项目记忆验证。"
```

Expected: memory sync 成功，claim 状态 completed。远程 push/PR 不在本计划内。

## 验证策略汇总

- 单元/组件：导航映射、选择回退、Provider 行为、Quick Setup 状态机。
- 静态布局契约：VUI 边界、单一页头、无 resize 侧栏、一次一个子页面、40–44px 控件和全高链路。
- 构建：完整 TypeScript + Vite build。
- 运行时：Launcher 加载本地 `main` 当前构建，API 200。
- 视觉：三档桌面视口、双主题、六分区、模型三模式、关键状态和高度测量。
- 治理：精确 claim、最小 staging、本地 fast-forward、memory sync、claim release；无远程动作。

## 方案审查循环

| 视角 | 挑战 | 证据 | 结论 |
| --- | --- | --- | --- |
| 用户意图 | 是否又变成局部样式修补 | 计划同时改变导航、唯一页头、单子页面、普通表单和 Provider 全高布局，并以三档截图验收 | PASS |
| 前置审查 | 是否遗漏现有配置入口 | live workspace 发现 `git-commit-model` 和 `git-commit-prompt` 未归属现有 group；已纳入“Git 提交”组合页 | PASS（已修正） |
| 实施者 | 4176 行 `ConfigRoute` 是否继续膨胀 | 导航模型和展示抽到 3 个新文件；状态/mutation ownership 留在 route，避免创建第二事实源 | PASS |
| 测试验证 | 静态字符串测试是否会产生假通过 | 同时使用纯函数断言、server-rendered markup、完整 Vitest/build、Launcher 和浏览器尺寸测量 | PASS |
| 维护与风险 | 是否改变 API、凭据或配置语义 | 所有变更限定在列出的前端文件；后端/API/config/version/package 为停止条件；凭据测试继续保留 | PASS |

## 方案修正

- 已修正：把错误文件名 `ConfigQuickProviderSetupPanel` 更正为 `ConfigQuickSetupPanel`；收尾时因根级 `web/ConfigRoute.layout.test.ts` 需要同步抽取后的导航断言，完整 claim 更新为 `claim-d4584ed61d84`。
- 已修正：把当前不可达的 `git-commit-model` 和 `git-commit-prompt` 纳入“工具与诊断 → Git 提交”。
- 已修正：工具类底层配置以五个本地页面组合，避免七个以上标签挤满 1280px 视口。
- 延后项：手机端适配、配置 schema/API 调整、Provider 新能力、应用顶部栏重构、远程 push/PR。
- 闸门：PASS。

## 账本更新

- 当前阶段：PLANNING。
- 已接受方案：固定桌面设置侧栏、唯一全局状态/保存页头、一级分区下单子页面、舒适表单密度和全高 Provider 工作区。
- 前置审查证据：`ConfigRoute.tsx` 当前组内成员全部渲染；侧栏存在宽高持久化/拖动；`ConfigProviderRegistryPanel.styles.ts` 仅使用 max-height；live workspace 暴露 20 个 sections，其中 Git 提交两项当前不可达。
- 复用决策：ADAPT。复用 `VSurface`、`VRouteHeader`、`VStatusStrip`、`VSplitWorkspace`、`VEntityList`、现有 Config panels 和状态机；无需外部组件研究或新依赖。
- 验证证据：规划前设置相关基线 72/72 PASS；live `/api/config/workspace` 已核对 sections/editorSections。
- 决策：移除侧栏 resize/collapse；`section` query 继续表示一级 group；组合页可以包含少量强相关底层 sections；原始编辑器移动但状态 ownership 不变。
- 未解决风险：实现期间 root `main` 或 active claim 可能变化，合入前必须重新 status/check；视觉高度需以 Launcher 运行时测量确认。
- 推荐下一阶段：`ccdawn-task-splitting`，因为本计划跨导航、route shell、普通设置、Provider workspace 和视觉 closeout，需判定顺序边界与 TDD 模式。
- 路由出口：`ccdawn-task-splitting`。

## 成功证据

- 用户可观察：六个一级分区清晰、每次一个子页面、按钮和字段足够大、Provider 管理填满可用高度、底部无整屏无意义空白。
- 工程证据：所有列出测试 0 failures、完整 Web build exit 0、closeout gate 通过、root `main` 复验通过。
- 运行证据：Launcher 当前构建、三档桌面双主题截图和高度测量、配置状态与 Provider 操作反馈正常。
- 治理证据：本地 fast-forward、项目记忆同步、claim completed；无远程发布。
