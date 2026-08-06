# VUI Component Design Specs

> **范围：全部 VUI 元素**，不限 page recipe。
> 含：primitives、forms、layout、display、aesthetic、product、provider。
> 权威：根 `AGENTS.md` §2 前端红线 + `docs/standards/development-standard.md` §9.1 + 本目录。

## 为什么要有

- 防止「看起来像 shadcn 就再抄一个按钮」的 **冗余组件**。
- 新建 / 扩展任何对外 `V*` 或 `product/*` 控件前，必须先有 **专门设计说明**。
- **设计选型时**只读本目录即可判断：能干什么、用在哪、怎么用 — 不必先翻源码。
- Agent 与人类共用同一索引，选型有据可查。

## 规则（硬）

1. **无设计说明，不合并新组件**
   - 新增 `V*` / `product/*` 导出前，必须在 [INDEX.md](./INDEX.md) 登记，并有对应设计文件中的专节（`## ComponentName`）。
2. **先复用，再扩展，最后新建**
   - 新建前在 INDEX 检索职责是否已被覆盖；职责重叠 → 扩展现有组件，禁止平行实现。
3. **每个组件专节必须可设计选型**
   - 至少包含 **功能 / 适用范围 / 使用方式** 三节（见下表）。缺一不可。
4. **`V*` 与 `VNative*` 不是两套系统**
   - 同一控件族必须在同一设计文件中写清 **何时用 V（带浮层/无障碍）vs VNative（密集零浮层）**。
5. **product 层禁止重复通用 primitive**
   - `product/` 只做领域组合；按钮/输入/表面必须组合 `VButton` / `VInput` / `VSurface` 等。
6. **renderer 不对外**
   - `renderers/shadcn/*` 无独立产品设计页；行为写在对应 `V*` 设计说明的「实现落点」节。
7. **浮层对齐门禁**
   - 产品面禁止手写 `createPortal` / `fixed inset-0` 对话框壳；模态用 `VDialog`/`VConfirmDialog`，锚定浮层用 `VPopover`/`VDropdownMenu`。
   - 总闸：`../vuiOverlayAlignmentGate.test.ts`（含 intentional keep 清单）。

## 设计说明最低字段

每个组件专节（`## Name`）必须包含（模板见 [_TEMPLATE.md](./_TEMPLATE.md)）：

| 字段 | 面向 | 含义 |
| --- | --- | --- |
| **功能** | 设计 / 产品 | 一句话：解决什么 UI 问题、用户感知是什么 |
| **适用范围** | 设计 / 产品 | 适用场景 + 不适用场景（并给出改用组件） |
| **使用方式** | 设计 / 实现 | 最小示例 + 关键 prop/槽位表；设计师能据此画状态与布局 |
| 非职责 | 实现 | 明确不做的事（防范围漂移） |
| 视觉与状态 | 设计 | tone/density/禁用/加载/空（按需） |
| 实现落点 | 实现 | 源文件 + renderer（如有） |
| 反冗余 | 实现 | 与相近组件的边界；禁止平行新建 |

> 旧写法「职责 / 何时使用」应迁移为上表三件套；门禁按 `### 功能` / `### 适用范围` / `### 使用方式` 标题校验。

## 目录

| 路径 | 内容 |
| --- | --- |
| [INDEX.md](./INDEX.md) | **全量组件索引**（选型入口） |
| [_TEMPLATE.md](./_TEMPLATE.md) | 新建组件用模板 |
| `primitives/` | 按钮、表面、反馈浮层 |
| `forms/` | 表单控件与字段行 |
| `layout/` | 页面 recipe + 页内结构件 |
| `display/` | 表格、指标、加载值 |
| `aesthetic/` | 密集工作台美学原子 |
| `product/` | Agent / Team 领域组合 |
| `provider.md` | VuiProvider |

## 机器门

`vuiComponentDesignContract.test.ts`：

- `index.ts` 导出的每个公共组件名必须出现在 `INDEX.md`；
- 每个 INDEX 条目必须指向存在的设计文件与 `## Name` 标题；
- 每个已实现组件专节必须含 `### 功能`、`### 适用范围`、`### 使用方式`。
