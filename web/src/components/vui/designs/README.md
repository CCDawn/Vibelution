# VUI Component Design Specs

> **范围：全部 VUI 元素**，不限 page recipe。
> 含：primitives、forms、layout、display、aesthetic、product、provider。
> 权威：根 `AGENTS.md` §2 前端红线 + `docs/standards/development-standard.md` §9.1 + 本目录。

## 为什么要有

- 防止「看起来像 shadcn 就再抄一个按钮」的 **冗余组件**。
- 新建 / 扩展任何对外 `V*` 或 `product/*` 控件前，必须先有 **专门设计说明**。
- Agent 与人类共用同一索引，选型有据可查。

## 规则（硬）

1. **无设计说明，不合并新组件**
   新增 `V*` / `product/*` 导出前，必须在 [INDEX.md](./INDEX.md) 登记，并有对应设计文件中的专节（`## ComponentName`）。
2. **先复用，再扩展，最后新建**
   新建前在 INDEX 检索职责是否已被覆盖；职责重叠 → 扩展现有组件，禁止平行实现。
3. **`V*` 与 `VNative*` 不是两套系统**
   同一控件族必须在同一设计文件中写清 **何时用 V（带浮层/无障碍）vs VNative（密集零浮层）**。
4. **product 层禁止重复通用 primitive**
   `product/` 只做领域组合；按钮/输入/表面必须组合 `VButton` / `VInput` / `VSurface` 等。
5. **renderer 不对外**
   `renderers/shadcn/*` 无独立产品设计页；行为写在对应 `V*` 设计说明的「实现」节。
6. **浮层对齐门禁**
   产品面禁止手写 `createPortal` / `fixed inset-0` 对话框壳；模态用 `VDialog`/`VConfirmDialog`，锚定浮层用 `VPopover`/`VDropdownMenu`。
   总闸：`../vuiOverlayAlignmentGate.test.ts`（含 intentional keep 清单）。

## 设计说明最低字段

每个组件专节必须包含（模板见 [_TEMPLATE.md](./_TEMPLATE.md)）：

| 字段 | 含义 |
| --- | --- |
| 职责 | 一句话：解决什么 UI 问题 |
| 非职责 | 明确不做的事（防范围漂移） |
| 何时使用 | 合法场景 |
| 何时不要用 | 应改用哪个现有组件 |
| API 要点 | 关键 props / 变体 |
| 视觉与状态 | tone/density/禁用/加载/空 |
| 实现落点 | 源文件 + renderer（如有） |
| 反冗余 | 与相近组件的边界 |

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
- 每个 INDEX 条目必须指向存在的设计文件与 `## Name` 标题。
