# Actions（按钮族）

## VButton

### 职责
产品主操作按钮：提交、确认、主要 CTA。

### 非职责
- 不负责路由导航语义（用 `VRouteLinkButton`）
- 不负责纯图标方钮（用 `VIconButton`）
- 不做密集表格内零浮层点击条（用 `VNativeButton`）

### 何时使用
- 工具条、表单提交、对话框主操作、空态 CTA

### 何时不要用
| 场景 | 改用 |
| --- | --- |
| 仅图标 | `VIconButton` |
| SPA 跳转且要保留 link 语义 | `VRouteLinkButton` |
| 画布节点/多行卡片点击命中区 | `VNativeButton` |

### API 要点
- `variant`: primary / secondary / danger 等
- `density`、`isDisabled`、`onPress`（兼容层）
- 可带 `icon`、`tooltip`、`disabledReason`

### 视觉与状态
- primary 实心；secondary 边框；disabled 降对比
- 长中文标签不截断布局（允许换行策略由调用方 class 控制）

### 实现落点
- `primitives/VButton.tsx` → `renderers/shadcn/ShadcnButton.tsx`

### 反冗余
- 禁止再新增 `PrimaryButton` / `HeroButton` 等平行按钮
- 扩展变体优先改 shared `buttonVariants`，不要新组件

---

## VIconButton

### 职责
方形图标按钮：刷新、关闭、更多。

### 非职责
- 带文字的主 CTA（用 `VButton`）

### 何时使用
- 工具条图标操作、紧凑 chrome

### 何时不要用
| 场景 | 改用 |
| --- | --- |
| 图标+文字 | `VButton` |
| 无障碍要求明确的文本按钮 | `VButton` + 可见 label |

### API 要点
- 必填 `label`（无障碍）
- `icon` 节点

### 实现落点
- `primitives/VIconButton.tsx`（组合 `VButton`）

### 反冗余
- 不要为每个图标各建一个 `VRefreshButton`

---

## VNativeButton

### 职责
原生 `<button>` 门面：密集操作、画布命中、多行卡片，避免浮层/复杂 slot。

### 非职责
- 不提供 Radix 浮层与完整 variant 系统

### 何时使用
- 组织画布节点、kanban 卡片脚注、超密集工具条

### 何时不要用
| 场景 | 改用 |
| --- | --- |
| 表单主提交、标准工具条 | `VButton` |
| 需要统一 primary 视觉 | `VButton` |

### API 要点
- 原生 button HTML 属性
- 样式几乎全由调用方 `className` 负责

### 实现落点
- `primitives/VNativeButton.tsx`

### 反冗余
- 与 `VButton` 共存是 **有意双轨**，边界写在「何时使用」；禁止第三种 button 门面

---

## VRouteLinkButton

### 职责
React Router 导航按钮：与 `VButton` 同视觉合同，语义是 link。

### 非职责
- 不发起 mutation

### 何时使用
- 「返回」「打开配置」等站内导航

### 何时不要用
| 场景 | 改用 |
| --- | --- |
| 同页动作 | `VButton` |
| 外链 | 原生 `a` + 既有外链样式约定 |

### 实现落点
- `primitives/VRouteLinkButton.tsx`

### 反冗余
- 不要 `VNavButton` / `VLink` 平行 API
