# Provider Management Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让桌面端“模型库 → 管理已有连接”在大量模型下仍易于浏览，并让每个模型与 Provider 操作的状态、可用性和反馈都准确对齐。

**Architecture:** 保留 `ConfigRoute` 作为异步请求、编辑器生命周期和工作区同步的唯一所有者；`ConfigProviderRegistryPanel` 只管理 Provider 切换后可丢弃的搜索/筛选会话状态并负责展示；把筛选、计数和模型操作语义放入 `configProviderLogic.ts` 纯函数，避免 JSX 与后端枚举耦合。现有 API、缓存与配置写入协议不变。

**Tech Stack:** React 19、TypeScript、VUI/HeroUI primitives、Tailwind CSS、Vitest、React DOM static rendering、Vite build、项目 Launcher。

## Global Constraints

- 仅优化桌面端，不新增手机端断点或移动布局。
- 先在 `C:\Users\17533\Desktop\Vibelution-worktrees\config-provider-management-polish` 创建 `codex/config-provider-management-polish`；根目录 `main` 只用于最终集成。
- 开始实现前运行 project memory guard 的 `status`、`check`、`claim`；结束时同步项目 memory 并 `release`。
- 不修改 Provider、模型目录、路由预览或配置写入的后端协议。
- 不把 observed/unknown 模型渲染成危险操作；只有真正可取消固定且未被引用的模型显示“取消固定”。
- API Key 始终使用密码输入，不在日志、测试快照或反馈消息中回显。
- 继续使用项目 VUI 组件；路由层不得直接引入 `@heroui/react`。
- 每个实现任务先写失败测试，再写最小实现，再运行该任务的聚焦测试。
- 前端行为变化需要 Launcher 刷新决定；若有 active work，必须先报告项目规定的阻塞文案，不绕过 guard。
- 版本影响预判：`patch`（用户可见的模型配置交互与布局修正），任务分支不直接修改版本文件。

---

### Task 0: 建立隔离 worktree 与前端写入 claim

**Files:** No product-code edits.

- [ ] **Step 1: 从 root `main` 检查 guard 与精确写入范围**

Run from `C:\Users\17533\Desktop\Vibelution`:

```powershell
$root = "C:\Users\17533\Desktop\Vibelution"
$python = Join-Path $root ".venv\Scripts\python.exe"
$guard = "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py"

& $python $guard $root status
& $python $guard $root check `
  --lane "web-workbench-surface" `
  --scope "web/src/routes/configProviderLogic.ts" `
  --scope "web/src/routes/configProviderLogic.test.ts" `
  --scope "web/src/routes/ConfigProviderRegistryPanel.tsx" `
  --scope "web/src/routes/ConfigProviderRegistryPanel.styles.ts" `
  --scope "web/src/routes/ConfigProviderRegistryPanel.test.tsx" `
  --scope "web/src/routes/ConfigRoute.tsx" `
  --scope "web/src/routes/ConfigRoute.layout.test.ts"
```

Expected: no overlapping active/ready claim. If overlap exists, stop before creating the branch and report the exact owner/scope.

- [ ] **Step 2: 创建任务 worktree**

```powershell
$worktree = "C:\Users\17533\Desktop\Vibelution-worktrees\config-provider-management-polish"
git -C $root status --short --branch
git -C $root worktree add -b "codex/config-provider-management-polish" $worktree main
git -C $worktree status --short --branch
```

Expected: root remains clean on `main`; task worktree is clean on `codex/config-provider-management-polish` and starts from current local `main`.

- [ ] **Step 3: 获取实现 claim 并记录返回的 claim id**

```powershell
$claim = & $python $guard $root claim `
  --lane "web-workbench-surface" `
  --scope "web/src/routes/configProviderLogic.ts" `
  --scope "web/src/routes/configProviderLogic.test.ts" `
  --scope "web/src/routes/ConfigProviderRegistryPanel.tsx" `
  --scope "web/src/routes/ConfigProviderRegistryPanel.styles.ts" `
  --scope "web/src/routes/ConfigProviderRegistryPanel.test.tsx" `
  --scope "web/src/routes/ConfigRoute.tsx" `
  --scope "web/src/routes/ConfigRoute.layout.test.ts" `
  --agent "codex-config-provider-management-polish" `
  --task "Polish Provider model management frontend" `
  --ttl-minutes 240 `
  --note "Desktop model search, filters, bounded table, action semantics, and Provider feedback." `
  --json | ConvertFrom-Json
$claim.claim.id
```

Expected: one active claim owned by `codex-config-provider-management-polish`. Keep the printed id for the closeout gate; do not claim `.docs/project-memory/**` during implementation.

---

### Task 1: 固化模型筛选、计数与操作语义

**Files:**

- Modify: `web/src/routes/configProviderLogic.ts`
- Modify: `web/src/routes/configProviderLogic.test.ts`

- [ ] **Step 1: 为纯逻辑写失败测试**

在 `configProviderLogic.test.ts` 增加覆盖：

- 搜索忽略大小写，并匹配 `modelRef`、`upstreamId` 与模型显示名。
- `all` 保持原顺序；筛选函数不修改输入数组。
- `pinned` 包含 `pinned`、`missing_remote`。
- `discovered` 包含 `observed`、`capability_unknown`、`protocol_unknown`、`unknown`。
- `unavailable` 只包含 `disabled`。
- 汇总数字与上述分组一致。
- `observed/unknown` 返回“未固定”；`disabled` 返回“不可用”。
- 可取消固定且 `liveReferenceCount === 0` 返回危险操作“取消固定”。
- 已固定但仍有引用时返回“使用中”与引用数，不返回可点击危险操作。

预期接口：

```ts
export type ProviderModelFilter =
  | "all"
  | "pinned"
  | "discovered"
  | "unavailable";

export type ProviderModelActionState =
  | { kind: "unpin"; label: "取消固定"; disabled: boolean; reason: string }
  | { kind: "in_use"; label: "使用中"; referenceCount: number }
  | { kind: "not_pinned"; label: "未固定" }
  | { kind: "unavailable"; label: "不可用" };

export function filterProviderModels(
  models: ConfigCatalogModel[],
  query: string,
  filter: ProviderModelFilter,
): ConfigCatalogModel[];

export function summarizeProviderModels(models: ConfigCatalogModel[]): {
  total: number;
  pinned: number;
  discovered: number;
  unavailable: number;
};

export function deriveProviderModelActionState(
  row: ProviderRegistryRow,
  model: ConfigCatalogModel,
  liveReferenceCount: number,
  disabled: boolean,
): ProviderModelActionState;
```

- [ ] **Step 2: 运行测试并确认失败原因是接口尚不存在**

Run:

```powershell
npm --prefix web test -- --run src/routes/configProviderLogic.test.ts
```

Expected: FAIL，缺少新导出或新断言失败；不得是测试环境或路径错误。

- [ ] **Step 3: 实现最小纯函数**

统一用小写、去首尾空白的查询串；用显式 `Set` 定义筛选分组。`deriveProviderModelActionState` 先处理不可用，再处理固定状态及 live refs，最后返回未固定。保留现有 `canUnpinProviderModel` 作为底层判断或兼容导出，避免无关调用方破坏。

- [ ] **Step 4: 重跑聚焦测试**

Run:

```powershell
npm --prefix web test -- --run src/routes/configProviderLogic.test.ts
```

Expected: PASS。

- [ ] **Step 5: 提交纯逻辑任务**

```powershell
git add -- web/src/routes/configProviderLogic.ts web/src/routes/configProviderLogic.test.ts
git commit -m "test(web): define Provider model presentation states"
```

---

### Task 2: 加入搜索、筛选、汇总和内部滚动表格

**Files:**

- Modify: `web/src/routes/ConfigProviderRegistryPanel.tsx`
- Modify: `web/src/routes/ConfigProviderRegistryPanel.styles.ts`
- Create: `web/src/routes/ConfigProviderRegistryPanel.test.tsx`
- Modify: `web/src/routes/ConfigRoute.layout.test.ts`

- [ ] **Step 1: 写面板静态渲染与源码契约失败测试**

使用 `renderToStaticMarkup` 构造至少 20 个模型，并验证：

- 搜索框有明确 accessible label/placeholder。
- 四个筛选入口显示总数、已固定、已发现、不可用数量。
- 默认展示全部模型，筛选后由纯函数提供稳定列表。
- 无模型时显示“该 Provider 暂无模型”；有模型但搜索无结果时显示“没有匹配的模型”。
- observed 行包含“未固定”且不包含该行的“取消固定”。
- 有 live refs 的固定模型显示“使用中 · N 个引用”，无危险按钮。
- 只有零引用的固定模型出现“取消固定”。
- 源码契约包含受限高度、`overflow-auto` 和 sticky table header，不引入 route-level `@heroui/react`。

若 static rendering 无法直接驱动本地 state，则把模型行渲染抽成同文件内的纯展示组件并导出测试，交互状态由浏览器 QA 覆盖；不要为测试增加生产环境专用入口。

- [ ] **Step 2: 运行面板与布局测试确认失败**

Run:

```powershell
npm --prefix web test -- --run src/routes/ConfigProviderRegistryPanel.test.tsx src/routes/ConfigRoute.layout.test.ts
```

Expected: FAIL，新工具栏、动作语义或滚动契约尚未实现。

- [ ] **Step 3: 实现 Provider 内的会话状态**

在 `ConfigProviderRegistryPanel` 中加入：

```ts
const [modelQuery, setModelQuery] = useState("");
const [modelFilter, setModelFilter] = useState<ProviderModelFilter>("all");

useEffect(() => {
  setModelQuery("");
  setModelFilter("all");
}, [selectedProviderId]);

const modelSummary = useMemo(
  () => summarizeProviderModels(provider.models),
  [provider.models],
);
const visibleModels = useMemo(
  () => filterProviderModels(provider.models, modelQuery, modelFilter),
  [provider.models, modelQuery, modelFilter],
);
```

工具栏使用现有 `VInput` 和 VUI 按钮/操作组；筛选按钮必须有 `aria-pressed`，选中态不能只依赖颜色。Provider 切换时重置搜索与筛选，不能写入全局 cache 或后端。

- [ ] **Step 4: 实现有界表格与语义化操作列**

- 表格区域使用桌面视口相关的最大高度与 `overflow-auto`，表头 sticky，页面主体不再因 20+ 模型无限增长。
- 操作列调用 `deriveProviderModelActionState`，按 discriminated union 渲染；只有 `kind === "unpin"` 渲染 danger button。
- unknown capability 改为低强调文本“未观测”，不再重复黄色 warning chip。
- 空目录与筛选无结果显示不同文案。
- 保留当前 Provider 列表/详情分栏比例，不增加移动端布局代码。

- [ ] **Step 5: 重跑测试并构建**

Run:

```powershell
npm --prefix web test -- --run src/routes/configProviderLogic.test.ts src/routes/ConfigProviderRegistryPanel.test.tsx src/routes/ConfigRoute.layout.test.ts
npm --prefix web run build
```

Expected: tests PASS；build PASS。若 bundle budget 是已存在的基线失败，保存当前分支与 `main` 的同命令对比，要求本任务无新增回归后再继续。

- [ ] **Step 6: 提交表格浏览体验任务**

```powershell
git add -- web/src/routes/ConfigProviderRegistryPanel.tsx web/src/routes/ConfigProviderRegistryPanel.styles.ts web/src/routes/ConfigProviderRegistryPanel.test.tsx web/src/routes/ConfigRoute.layout.test.ts
git commit -m "feat(web): streamline Provider model browsing"
```

---

### Task 3: 对齐 Provider 按钮的进行中、激活、成功与失败反馈

**Files:**

- Modify: `web/src/routes/ConfigProviderRegistryPanel.tsx`
- Modify: `web/src/routes/ConfigProviderRegistryPanel.styles.ts`
- Modify: `web/src/routes/ConfigProviderRegistryPanel.test.tsx`
- Modify: `web/src/routes/ConfigRoute.tsx`
- Modify: `web/src/routes/ConfigRoute.layout.test.ts`

- [ ] **Step 1: 写反馈契约失败测试**

覆盖三类动作：

- 发现：idle “发现”、busy “发现中…”、成功“发现 N 个模型”或“目录已刷新”、失败消息与可重试入口。
- API Key：编辑器开启时顶部按钮有 active/`aria-pressed`，保存时“保存中…”，失败保留输入，取消或成功后清除输入；静态标记不含 key value。
- 路由：编辑器开启时顶部按钮有 active/`aria-pressed`，预览时“生成预览中…”，应用时“更新中…”；应用失败保留可恢复的预览。
- 切换 Provider 会关闭 credential/route 编辑器并清除只属于旧 Provider 的反馈。

面板反馈数据使用明确类型：

```ts
export type ProviderActionKind = "discover" | "credential" | "route";

export type ProviderActionFeedback = {
  kind: ProviderActionKind;
  providerId: string;
  phase: "busy" | "success" | "error";
  message: string;
} | null;
```

新增 props：

```ts
activeCredentialProviderId: string;
activeRouteProviderId: string;
actionFeedback: ProviderActionFeedback;
```

- [ ] **Step 2: 运行测试确认现有固定标签与全局 disabled 行为不满足契约**

Run:

```powershell
npm --prefix web test -- --run src/routes/ConfigProviderRegistryPanel.test.tsx src/routes/ConfigRoute.layout.test.ts
```

Expected: FAIL，缺少 active/busy/feedback props 或对应文案。

- [ ] **Step 3: 让 `ConfigRoute` 成为反馈状态唯一所有者**

新增 `providerActionFeedback` state，但保留现有 `busyAction` 供页面级互斥和顶层状态条使用。每个 handler 遵循：

```ts
setProviderActionFeedback({
  kind: "discover",
  providerId,
  phase: "busy",
  message: "正在发现模型…",
});
try {
  const models = await discoverProvider(providerId);
  await syncStructuredWorkspace();
  setProviderActionFeedback({
    kind: "discover",
    providerId,
    phase: "success",
    message: models.length > 0 ? `发现 ${models.length} 个模型` : "目录已刷新",
  });
  return models;
} catch (error) {
  setProviderActionFeedback({
    kind: "discover",
    providerId,
    phase: "error",
    message: formatProviderActionError(error),
  });
  throw error;
}
```

对 credential/route 使用同一状态结构。错误文案复用已有受控格式化逻辑，不泄露 API Key、请求正文或完整响应。不要用任意 timeout 自动清除反馈；下一次同类动作、Provider 切换或显式关闭编辑器时再替换/清除。

- [ ] **Step 4: 对齐顶部按钮和相邻反馈区**

- “发现”仅在自己的 feedback 为 busy 时显示“发现中…”。
- “设置 API Key”和“修改路由”在对应编辑器打开时设置 `aria-pressed="true"` 与稳定 active 样式。
- busy 只禁用会冲突的写操作；不要把所有中性状态伪装成 disabled danger buttons。
- 成功/失败反馈显示在 Provider 标题/动作区域附近，使用 status semantics 与 `aria-live="polite"`；错误态保留重试路径。
- API Key editor 保持 password 类型；取消必须清空输入。
- 路由预览应用失败时不得清空已有 preview。

- [ ] **Step 5: Provider 切换时清理旧编辑器状态**

选择新 Provider 时同时清理：

```ts
setEditingCredentialProviderId("");
setCredentialValue("");
setEditingRouteProviderId("");
setRoutePreview(null);
setProviderActionFeedback(null);
```

仅清理本地编辑会话，不回滚已成功写入的配置。

- [ ] **Step 6: 重跑聚焦测试**

Run:

```powershell
npm --prefix web test -- --run src/routes/configProviderLogic.test.ts src/routes/ConfigProviderRegistryPanel.test.tsx src/routes/ConfigRoute.layout.test.ts
```

Expected: PASS。

- [ ] **Step 7: 提交动作反馈任务**

```powershell
git add -- web/src/routes/ConfigProviderRegistryPanel.tsx web/src/routes/ConfigProviderRegistryPanel.styles.ts web/src/routes/ConfigProviderRegistryPanel.test.tsx web/src/routes/ConfigRoute.tsx web/src/routes/ConfigRoute.layout.test.ts
git commit -m "fix(web): align Provider action feedback"
```

---

### Task 4: 完成桌面端视觉 QA 与回归验证

**Files:**

- Modify only if QA exposes a defect: files already listed in Tasks 1–3
- Add bounded runtime-scene evidence only if existing frontend/config logging policy requires it

- [ ] **Step 1: 运行完整的相关自动化验证**

Run:

```powershell
npm --prefix web test -- --run src/routes/configProviderLogic.test.ts src/routes/ConfigProviderRegistryPanel.test.tsx src/routes/ConfigRoute.layout.test.ts
npm --prefix web run build
git diff --check main...HEAD
git status --short --branch
```

Expected: tests PASS、build PASS、diff check 无输出；工作树只含当前任务文件。

- [ ] **Step 2: 通过 Launcher 刷新决定进入真实页面**

先重新检查 guard。无 active work 时通过 Launcher 刷新；若被 active work 阻塞，原样报告：

`有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。`

不得直接重启前后端绕过 Launcher。只有用户再次提供精确短语 `确认强制接管并刷新 Vibelution` 才能走受控强制接管流程。

- [ ] **Step 3: 浏览器验证桌面宽度与主题**

在 `/config` → “模型库” → “管理已有连接”验证 1280、1600、1920 px；light/dark 均覆盖：

- Provider 列表与详情列不重叠，长 Provider/模型名不挤压操作列。
- 0、1、20+ 模型下表格高度合理；20+ 时表头固定，滚动只发生在模型区。
- 搜索大小写、四种筛选、无结果与清空操作正常。
- observed 行为“未固定”，有引用行为“使用中”，只有可取消固定行显示红色按钮。
- repeated unknown capability 已降为“未观测”低强调文本。
- 三个 Provider 动作的 idle/active/busy/success/error 对齐；键盘 focus ring 和 `aria-pressed` 可辨识。
- 不输入真实 API Key，不点击会改变用户配置的“取消固定”或“应用路由”；写操作反馈由自动化测试和受控测试数据覆盖。

保存必要的局部截图或 runtime-scene 证据，避免记录完整配置、密钥或无界输出。

- [ ] **Step 4: 修复 QA 暴露的问题并重复最小验证**

每个新缺陷先补回归测试，再做最小修复；重复对应聚焦测试、build 与受影响宽度/主题检查。不要借 QA 扩展到快速配置、高级设置或移动端重构。

- [ ] **Step 5: 自审任务差异**

核对：

- 已批准设计中的筛选分组、操作语义、反馈文案、安全约束全部有测试或浏览器证据。
- 没有后端 API、DTO、配置格式和缓存行为变化。
- 没有直接 HeroUI import、秘密回显、测试专用生产接口或无关格式化。
- 对 build/bundle 的结论来自本轮新鲜输出。

---

### Task 5: 本地集成、项目记忆与 claim 收尾

**Files:**

- Modify: `.docs/project-memory/` 中由项目 memory 工具选择的最小相关文件

- [ ] **Step 1: 在任务 worktree 运行 claim-bound closeout gate**

从 guard `status --json` 解析当前任务的 active claim，避免使用过期或他人的 claim id：

```powershell
$root = "C:\Users\17533\Desktop\Vibelution"
$worktree = "C:\Users\17533\Desktop\Vibelution-worktrees\config-provider-management-polish"
$python = Join-Path $root ".venv\Scripts\python.exe"
$guard = "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py"
$guardState = & $python $guard $root status --json | ConvertFrom-Json
$implementationClaim = $guardState.claims | Where-Object {
  $_.agent -eq "codex-config-provider-management-polish" -and $_.status -eq "active"
} | Select-Object -First 1
if (-not $implementationClaim) { throw "Active implementation claim not found." }

Push-Location $worktree
try {
  $closeout = & $python "scripts\local_quality_gate.py" closeout `
    --base main `
    --claim-id $implementationClaim.id | ConvertFrom-Json
  if ($closeout.exit_code -ne 0 -or $closeout.outcome -ne "passed") {
    $closeout | ConvertTo-Json -Depth 8
    throw "Local closeout gate failed."
  }
  $closeout.manifest_path
} finally {
  Pop-Location
}
```

Expected: closeout manifest is `passed` and binds current local `main`, task HEAD, selected validation commands and the exact implementation claim. The gate does not merge or release the claim.

- [ ] **Step 2: 通过 merge gates 后自合并到本地 `main`**

确认 task worktree clean、聚焦测试/build/浏览器 QA 新鲜通过、无 active claim 冲突，再从 root 执行 fast-forward merge：

```powershell
git -C $worktree status --short --branch
git -C $root status --short --branch
Push-Location $worktree
try {
  $manifest = Join-Path $worktree ".runtime\quality_gates\config-provider-management-polish.json"
  $verified = & $python "scripts\local_quality_gate.py" verify-manifest `
    --manifest $manifest `
    --base main | ConvertFrom-Json
  if ($verified.exit_code -ne 0 -or $verified.outcome -ne "passed") {
    $verified | ConvertTo-Json -Depth 8
    throw "Closeout manifest is stale or invalid."
  }
} finally {
  Pop-Location
}
git -C $root merge --ff-only "codex/config-provider-management-polish"
```

若 `main` 已前进导致 manifest 或 fast-forward 失败，先在任务 worktree 合并最新本地 `main`，只解决本任务范围内的小冲突，提交并重跑 Task 4 与 closeout；大范围、跨 lane 或语义不明确冲突必须停止并汇报。

- [ ] **Step 3: 在 root `main` 重跑决定性验证**

Run:

```powershell
npm --prefix web test -- --run src/routes/configProviderLogic.test.ts src/routes/ConfigProviderRegistryPanel.test.tsx src/routes/ConfigRoute.layout.test.ts
npm --prefix web run build
git status --short --branch
```

Expected: tests/build PASS；root 位于 `main` 且无本任务遗留 dirty changes。

- [ ] **Step 4: 在 root 上获取单写者 memory claim 并同步**

先确认 memory surfaces clean，再获取独立 claim；若已有 memory writer 或这些文件有无关改动，停止同步并在最终报告给出同样的 lane/focus/update 提案，不覆盖现有状态。

```powershell
$memoryChanges = @(git -C $root status --short -- ".docs/project-memory" "PROJECT_MEMORY.html")
if ($memoryChanges.Count -gt 0) {
  $memoryChanges
  throw "Project-memory surfaces contain pre-existing changes."
}

$memoryClaim = & $python $guard $root claim `
  --lane "web-workbench-surface" `
  --scope ".docs/project-memory/**" `
  --scope "PROJECT_MEMORY.html" `
  --agent "codex-config-provider-management-polish-memory" `
  --task "Sync Provider management polish memory" `
  --ttl-minutes 60 `
  --note "Serialize validated local-main Provider management UI result." `
  --json | ConvertFrom-Json

$sync = "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\sync_project_memory.py"
& $python $sync $root `
  --lane "web-workbench-surface" `
  --focus "Provider model management frontend polished" `
  --update "Desktop Provider management now has local model search and status filters, a bounded sticky-header table, accurate unpin and live-reference semantics, low-emphasis unobserved capabilities, and aligned discover, credential, and route feedback. Focused tests, web build, Launcher decision, and desktop browser QA were recorded; version impact is patch."
if ($LASTEXITCODE -ne 0) {
  & $python $guard $root release --claim-id $memoryClaim.claim.id --status blocked --reason "Provider management memory sync failed."
  throw "Project-memory sync failed."
}
```

- [ ] **Step 5: 审核并提交 memory 工具的精确输出**

```powershell
$memoryFiles = @(git -C $root diff --name-only -- ".docs/project-memory" "PROJECT_MEMORY.html")
if ($memoryFiles.Count -eq 0) { throw "Project-memory sync produced no diff." }
$memoryFiles | ForEach-Object { git -C $root add -- $_ }
git -C $root diff --cached --check
git -C $root commit -m "docs(memory): record Provider management polish"
& $python $guard $root release `
  --claim-id $memoryClaim.claim.id `
  --status completed `
  --reason "Provider management polish memory synced from validated local main."
```

Expected: only sync-generated project-memory files are committed; memory claim is completed.

- [ ] **Step 6: 释放实现 claim、清理本任务资源并报告**

```powershell
& $python $guard $root release `
  --claim-id $implementationClaim.id `
  --status completed `
  --reason "Provider management polish merged to local main; focused tests, build, Launcher decision, browser QA, and memory sync completed."

git -C $root worktree remove $worktree
git -C $root branch -d "codex/config-provider-management-polish"
git -C $root worktree prune
git -C $root status --short --branch
```

只有在 worktree clean、分支已合并且上述 release 成功后才清理本任务资源；不得删除其他 worktree、分支或 claim。

最终报告包含：用户可见变化、提交与本地合并状态、测试/build/浏览器证据、Launcher 刷新结果、project-memory 与 claim 状态、版本影响 `patch`、未执行的破坏性操作、剩余风险。未经用户明确授权，不 push、不创建 PR。
