# Forms（表单控件）

## 选型总表（防冗余）

| 需求 | 使用 |
| --- | --- |
| 标准表单、需要统一外观 | `VInput` / `VTextarea` / `VSelect` / `VCheckbox` |
| 密集 ops、零浮层、完全自控 class | `VNative*` |
| 标签+控件一行 | `VFieldRow` 包住控件 |
| 字符串 value 的简化 select | `VStringSelect` |

禁止再增加第四套 Input。

---

## VInput

### 职责
标准文本输入（shadcn 外观）。

### 非职责
- 不做搜索框业务逻辑（调用方处理 debounce）

### 何时使用 / 不要用
- 用：设置页、创建表单
- 不要用：画布工具条极密输入 → `VNativeInput`

### 实现落点
- `forms/VInput.tsx` → `ShadcnInput`

---

## VNativeInput

### 职责
原生 input 门面。

### 何时使用
- 密集筛选条、自定义高度 class 很多的场景

### 反冗余
- 与 `VInput` 双轨有意；新场景默认 `VInput`

---

## VTextarea

### 职责
多行文本（标准）。

### 实现落点
- `forms/VTextarea.tsx` → `ShadcnTextarea`

---

## VNativeTextarea

### 职责
多行原生 textarea。

### 何时使用
- 审查备注、节点 purpose 等密集表单

---

## VSelect

### 职责
可访问选择器（**Radix Select** / shadcn 风格），支持 `selectedKey` / `onSelectionChange`、选项 description、portal 下拉。

### 视觉与状态
- Trigger 与 `VInput` 同 control chrome（border / ring focus）
- 下拉：panel 表面 + 高亮行 + check indicator
- 表单 `name` 时输出 hidden input 便于原生提交

### 何时不要用
| 场景 | 改用 |
| --- | --- |
| 简单 string + 原生 option 列表、极低成本 | `VNativeSelect` 或 `VStringSelect` |
| 需要搜索过滤大量选项 | 暂用调用方 Combobox 方案（未建 `VCombobox` 前） |

### 实现落点
- `forms/VSelect.tsx` → `renderers/shadcn/ShadcnSelect.tsx`（`@radix-ui/react-select`）

---

## VNativeSelect

### 职责
原生 `<select>`。

### 何时使用
- 选项少、需极低成本、密集面板

---

## VStringSelect

### 职责
以 string 为 value 的选择封装，减少 key 样板代码。

### 何时使用
- 配置项枚举、过滤器

### 反冗余
- 不要再做 `VEnumSelect`；扩展本组件

---

## VCheckbox

### 职责
复选框。

### 实现落点
- `forms/VCheckbox.tsx` → `ShadcnCheckbox`

---

## VFieldRow

### 职责
标签 + 控件 + 可选说明的表单行。

### 非职责
- 不做整表校验引擎

### 何时使用
- 设置表单每一行

### 反冗余
- 禁止 route 复制 `label > span + input` 结构而不用 FieldRow（例外：超自定义网格）
