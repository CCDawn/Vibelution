# Provider

## VuiProvider

### 职责
VUI 根 Provider：`data-vui-provider="shadcn"`，主题/密度边界。

### 非职责
- 不做业务路由状态

### 何时使用
- 应用根（Workbench 已挂）

### 实现落点
- `VuiProvider.tsx` + `design/vui-provider-theme.css`

### 反冗余
- 禁止第二 Provider 包一层 Hero/其它 UI 库
