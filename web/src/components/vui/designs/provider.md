# Provider

## VuiProvider

### 功能
VUI 根 Provider：挂载 `data-vui-provider="shadcn"`，划定主题/密度与设计 token 边界。

### 适用范围
- **适用**：应用根（Workbench 已挂一处）。
- **不适用**：业务路由状态；第二套 UI 库 Provider。

| 场景 | 选择 |
| --- | --- |
| 应用根包裹 | 唯一 `VuiProvider` |
| 业务 store | 非本组件 |

### 使用方式
```tsx
import { VuiProvider } from "@/components/vui";

<VuiProvider>
  <App />
</VuiProvider>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| children | 子树 | 全应用只挂一次 |

### 非职责
- 不做业务路由状态。

### 实现落点
- `VuiProvider.tsx` + `design/vui-provider-theme.css`

### 反冗余
- 禁止第二 Provider 包一层 Hero/其它 UI 库。
