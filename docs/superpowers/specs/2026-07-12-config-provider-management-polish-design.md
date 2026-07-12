# 模型配置管理面板交互与布局优化设计

**Status:** approved-design
**Date:** 2026-07-12
**Owner:** web-workbench-surface
**Target:** `/config` → 模型库 → 管理已有连接
**Version impact:** patch

## 1. 目标

把已有 Provider 的模型管理面从“整页无限长表格和大量危险按钮”收敛为一个有界、可搜索、状态明确的桌面工作区。用户应当能快速判断：当前 Provider 是否可用、哪些模型只是发现、哪些模型已经固定、哪些模型正在被引用，以及每个操作是否真的可执行。

## 2. 范围

### 2.1 本轮包含

- 模型表格使用固定表头和内部滚动，避免模型数量直接拉长整个设置页。
- 增加模型搜索、状态筛选和数量摘要。
- 修正 `observed`、`pinned`、`missing_remote`、`disabled` 与 live reference 的操作呈现。
- 统一“发现”“设置 API Key”“修改路由”的 idle、busy、active、success 和 error 反馈。
- 降低重复 `unknown · 未观测` 能力标签的视觉噪声。
- 检查连接、模型、协议与诊断四个标签页的对齐、焦点和空状态。

### 2.2 明确不做

- 不做手机端或触屏布局。
- 不新增 Provider、模型目录、凭据或配置事实源。
- 不新增后端接口，不改变 operator config 写入路径。
- 不改变模型固定、取消固定、live reference 保护和 route preview 的后端授权语义。
- 不把快速配置与管理已有连接重新堆叠在同一页面。

## 3. 信息层级与布局

Provider 管理继续使用左侧 30% Provider 列表、右侧 70% 详情的桌面双栏。模型标签页内部按三层组织：

1. **摘要与筛选栏**：模型总数、已固定、已发现、不可用；搜索框；状态筛选。
2. **有界模型表格**：sticky 表头，表体内部纵向滚动，必要时局部横向滚动。
3. **结果反馈**：搜索无结果、没有发现模型、发现失败和刷新成功的邻近提示。

表格高度使用桌面视口约束，页面本身只保留工作台级滚动。模型数量增加时不得继续扩大页面高度。

## 4. 模型列表行为

搜索匹配 `modelRef`、`upstreamId` 和显示名称，大小写不敏感。状态筛选提供：

- 全部；
- 已固定：`pinned`、`missing_remote`；
- 已发现：`observed`、`capability_unknown`、`protocol_unknown`、`unknown`；
- 不可用：`disabled`。

搜索与筛选只作用于后端返回的当前 Provider 模型数组，不修改 React Query cache、Provider draft 或正式配置。切换 Provider 时重置搜索和筛选，避免将上一 Provider 的过滤状态误带入下一 Provider。

## 5. 操作语义

| 模型状态 | 操作列呈现 | 行为 |
| --- | --- | --- |
| `observed` / unknown 类 | 中性文本“未固定” | 不渲染危险按钮 |
| `pinned` / `missing_remote` 且无 live reference | “取消固定”危险按钮 | 调用现有取消固定路径 |
| `pinned` / `missing_remote` 且有 live reference | 中性“使用中”状态与引用数量 | 不提供可点击危险操作；解释保护原因 |
| `disabled` | 中性“不可用” | 不提供取消固定操作 |

禁用按钮不能代替语义：当操作根本不适用时不渲染按钮；只有操作适用但暂时因全局 busy/只读被阻止时才使用 disabled 状态。

## 6. Provider 操作反馈

### 6.1 发现

- idle：显示“发现”。
- busy：按钮原位显示“发现中…”，保持宽度稳定，禁用重复提交。
- success：在按钮附近显示“发现 N 个模型”或“目录已刷新”，不使用全局远端提示作为唯一反馈。
- error：在 Provider 详情头或当前标签页显示有界错误；按钮恢复可重试。

### 6.2 设置 API Key

- 点击后按钮呈 active/pressed 状态，并在 Provider 详情邻近区域打开凭据编辑面。
- 输入框使用 password，不回显旧值。
- 保存时显示“保存中…”，成功后关闭编辑面并刷新凭据状态；失败时保留输入并显示有界错误。
- 取消时清空本次输入。

### 6.3 修改路由

- 点击后按钮呈 active/pressed 状态，并打开现有 route preview 编辑面。
- 预览时显示“生成预览中…”，得到 token 后切换为影响确认状态。
- 应用时显示“更新中…”，成功后关闭编辑面；失败保留可恢复预览。

三个操作共享一致的按钮高度、图标位置、busy 文案和邻近反馈，不能只依赖颜色表达状态。

## 7. 能力来源呈现

- 有明确 supported/unsupported 观测时保留状态、来源与置信度。
- 所有能力均为 unknown 时，显示低强调文本“未观测”，不重复渲染黄色警告胶囊。
- 仍保留 `data-model-availability` 和能力来源字段，便于测试和诊断，不隐瞒真实状态。

## 8. 组件与状态边界

| 模块 | 职责 |
| --- | --- |
| `ConfigProviderRegistryPanel` | Provider 管理布局、操作反馈、模型搜索和筛选会话状态。 |
| `configProviderLogic.ts` | 纯模型过滤、状态分组和操作呈现判定。 |
| `ConfigRoute` | API 调用、workspace 同步、busy/error/success 结果及正式配置边界。 |
| VUI | 输入、按钮、状态、表格、焦点和可访问性基础能力。 |

搜索和筛选属于面板会话状态。API busy/result 由 `ConfigRoute` 统一拥有，并通过 typed props 传入面板；面板不得直接调用 API 或修改 canonical workspace。

## 9. 错误与恢复

- Provider 切换期间清空正在编辑的凭据、路由表单和模型过滤条件。
- 发现失败保留上一份模型目录并标记失败，不把旧目录伪装成最新成功结果。
- 取消固定失败保留当前行，不提前从表格移除。
- 空目录与过滤无结果使用不同文案：前者提示运行发现，后者提示调整搜索或筛选。
- busy 状态不得改变操作栏或表格列宽。

## 10. 可访问性

- 搜索输入有可见标签或明确 `aria-label`。
- 状态筛选支持键盘和焦点可见性。
- 标签页保持 `aria-pressed`，Provider 操作按钮增加 `aria-pressed` 或等价 active 状态。
- sticky 表头在浅色、深色主题下均保持对比度。
- “使用中”“未固定”“不可用”使用文字，不只使用颜色。

## 11. 验证计划

### 11.1 自动测试

- 纯逻辑：搜索字段、大小写、四类筛选、稳定顺序和不修改输入数组。
- 操作语义：observed/disabled 不渲染取消固定；pinned/missing_remote 的 live-reference 门禁。
- 反馈契约：发现、API Key、路由操作的 idle/busy/active/success/error 文案与状态。
- 布局契约：sticky 表头、内部滚动、固定桌面双栏、无 route 级 HeroUI 直引。
- 安全契约：API Key 不进入展示文本、错误摘要或持久缓存。

### 11.2 浏览器验证

- 1280×720、1600×900、1920×1080。
- 浅色和深色主题。
- 0、1、20+ 模型，最长中英文模型名。
- 全部、已固定、已发现、不可用和搜索无结果。
- 发现中/成功/失败，API Key 编辑/保存失败，路由预览/应用失败。
- 无页面级横向溢出、无表格无限拉长、无按钮跳动、无 console error。

## 12. 发布判断

- Logging：不新增后端事件；复用现有 Provider mutation 与 discovery 有界日志。
- Developer/formal mode：parity preserved。
- Runtime refresh：用户测试前 required。
- Project memory：合入本地 main 后同步 `web-workbench-surface`。
- Version impact：patch。

## 13. 验收标准

- 20+ 模型不会把设置页扩展成无限长页面。
- 用户能通过搜索和筛选在一次扫描内找到目标模型。
- observed、disabled、pinned 和 live-reference 模型的操作语义无歧义。
- 只有真正可取消固定的模型显示危险按钮。
- Provider 三个主要操作在原位给出一致、可恢复的反馈。
- 三个桌面视口和双主题真实浏览器检查通过。
