# 产品 UI 注册表（现行）

> 从根 `DESIGN.md` 提炼的**产品级**设计立场。完整历史快照见 [`../archive/product/DESIGN.md`](../archive/product/DESIGN.md)。
> **组件与 token 实现权威**：[`web/src/components/vui/`](../../web/src/components/vui/README.md) + [`designs/`](../../web/src/components/vui/designs/README.md) + 开发标准 §9.1。
> 本文件不重复 VUI 组件表，也不与 CSS 变量抢真源。

## 注册表（Register）

Vibelution 使用 **product** 注册表：设计服务重复工程工作、运行诊断与受控进化。默认视觉模式是紧凑、ops 向、控制台感。

## 主题

- **暗色**为工作台主参考（长时调试、日志、diff）。
- 亮色为支持的备选主题。

## 布局与密度

- 稳定 app shell：顶栏、路由工作区、侧栏、面板、页签、分栏。
- 路由面可扫读，重要状态优先可见。
- 禁止营销式大 hero / 着陆页分区。
- 默认**不嵌套卡片**；用间距、分隔线、标题和对齐建层次。
- 卡片用于可重复条目、摘要、模态或真正成帧的工具，不是默认分组方案。

## 组件与实现边界

- 产品控件走 **VUI `V*`**；交互实现只在 `renderers/shadcn`。
- 禁止路由直连 renderer、禁止第二套设计系统、禁止回退 HeroUI。
- 图标优先现有 `lucide-react`；不引入第二图标族，除非有 ADR。
- 交互控件在可能出现的状态下要可辨：default / hover / focus-visible / active / disabled / loading / error / success。

## 动效

- 服务于状态沟通，不服务于装饰。
- 常规反馈约 100–250ms；大布局变化 300–500ms 仅在有助于定向时。
- 任务路由禁止开场动画。
- 尊重 reduced-motion。

## 文案

- 短、具体、可操作。按钮写动作：`Save changes`、`Open logs`。
- 破坏性操作点明对象与后果。
- 错误说明：发生了什么、已知原因、下一步。
- 领域词稳定：Agent、Turn、Tool、Workbench、Self-Evolution、Supervised Evolution、Gym、Case、Attempt、Trace、Decision Record 等（见 [domain.md](../agents/domain.md)）。

## 产品级禁令（Anti-patterns）

- 通用 SaaS 着陆页美学、大装饰 hero
- 嵌套卡片、同质 icon-heading-text 网格
- 装饰性紫蓝渐变、玻璃态默认表面
- 控件/表格/日志中的 display 装饰字体
- 延误任务的动效
- 可用内联/渐进披露时，不把模态当第一方案

## 验证期望

前端视觉变更按开发标准分级验证：相关路由状态、对比度、焦点、窄窗、溢出、加载/空态，结果仍应读起来像 Vibelution 工作台，而不是通用 AI 生成壳。

## 历史快照注意

归档 `DESIGN.md` 中的具体 CSS 变量名、圆角像素等可能滞后；改 token/组件前查现行 VUI designs 与主题 CSS。
