# Forms（表单控件）

## 选型总表（防冗余）

| 需求 | 使用 |
| --- | --- |
| 标准表单、统一外观 | `VInput` / `VTextarea` / `VSelect` / `VCheckbox` |
| 密集 ops、零浮层、自控 class | `VNative*` |
| 标签+控件一行 | `VFieldRow` 包住控件 |
| 字符串 value 的简化 select | `VStringSelect` |

禁止再增加第四套 Input。

---

## VInput

### 功能
标准单行文本输入（shadcn 外观），用于设置与创建表单。

### 适用范围
- **适用**：设置页、创建表单、需要统一 control chrome 的输入。
- **不适用**：画布/极密筛选条 → `VNativeInput`；多行 → `VTextarea`。

| 场景 | 选择 |
| --- | --- |
| 配置文本字段 | `VInput` |
| 密集筛选搜索框 | `VNativeInput` |

### 使用方式
```tsx
import { VFieldRow, VInput } from "@/components/vui";

<VFieldRow label="名称">
  <VInput value={name} onChange={(e) => setName(e.target.value)} />
</VFieldRow>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| value / onChange | 受控文本 | 与原生 input 一致 |
| disabled / placeholder | 状态 | 错误文案放 FieldRow 旁 |

### 非职责
- 不做搜索 debounce 等业务逻辑。

### 实现落点
- `forms/VInput.tsx` → `ShadcnInput`

---

## VNativeInput

### 功能
原生 input 门面：密集筛选、高度/class 完全由域样式控制。

### 适用范围
- **适用**：密集筛选条、自定义高度很多的场景。
- **不适用**：标准设置表单 → 默认 `VInput`。

| 场景 | 选择 |
| --- | --- |
| 设置表单 | `VInput` |
| 工具条内搜索 | `VNativeInput` |

### 使用方式
```tsx
import { VNativeInput } from "@/components/vui";

<VNativeInput className={styles.search} value={q} onChange={...} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| 原生 input 属性 | type/value/onChange | 视觉靠 className |

### 反冗余
- 与 `VInput` 双轨有意；新场景默认 `VInput`。

---

## VTextarea

### 功能
标准多行文本输入，与 `VInput` 同 control 族外观。

### 适用范围
- **适用**：设置备注、中等长度说明字段。
- **不适用**：审查/节点超密备注 → `VNativeTextarea`。

| 场景 | 选择 |
| --- | --- |
| 设置页多行 | `VTextarea` |
| 密集审查备注 | `VNativeTextarea` |

### 使用方式
```tsx
import { VTextarea } from "@/components/vui";

<VTextarea value={note} onChange={(e) => setNote(e.target.value)} rows={4} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| rows / value | 高度与内容 | 长文案区域可滚动 |

### 实现落点
- `forms/VTextarea.tsx` → `ShadcnTextarea`

---

## VNativeTextarea

### 功能
多行原生 textarea 门面，供密集表单与自定义 class 主导的场景。

### 适用范围
- **适用**：审查备注、节点 purpose 等密集表单。
- **不适用**：标准设置页 → `VTextarea`。

| 场景 | 选择 |
| --- | --- |
| 密集备注 | `VNativeTextarea` |
| 设置说明 | `VTextarea` |

### 使用方式
```tsx
import { VNativeTextarea } from "@/components/vui";

<VNativeTextarea className={styles.note} value={note} onChange={...} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| 原生 textarea 属性 | value/onChange/rows | 视觉靠 className |

---

## VSelect

### 功能
可访问选择器（Radix Select / shadcn）：支持 description、portal 下拉、非 string key。

### 适用范围
- **适用**：需要 description / 非 string key 的选择。
- **不适用**：常见 string 枚举 → **优先 `VStringSelect`**；零 portal 极密 → `VNativeSelect`（尽量少用）；大量可搜索选项 → 暂用调用方 Combobox。

| 场景 | 选择 |
| --- | --- |
| 字符串枚举 | `VStringSelect` |
| 选项带 description | `VSelect` |
| 必须零 portal | `VNativeSelect`（慎用） |

### 使用方式
```tsx
import { VSelect } from "@/components/vui";

<VSelect
  selectedKey={key}
  onSelectionChange={setKey}
  items={[{ key: "a", label: "A", description: "..." }]}
/>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| selectedKey / onSelectionChange | 选中态 | 与 form name 可联动 hidden input |
| items | 选项 | 可含 description |

### 实现落点
- `forms/VSelect.tsx` → `ShadcnSelect`

---

## VNativeSelect

### 功能
原生 `<select>` 门面（dense 双轨保留）。

### 适用范围
- **适用**：选项极少且必须零 portal、Radix 会破坏布局时。
- **不适用**：默认新场景 → `VStringSelect`；勿在 product routes 扩大使用面。

| 场景 | 选择 |
| --- | --- |
| 新表单枚举 | `VStringSelect` |
| 极密零 portal | `VNativeSelect`（例外） |

### 使用方式
```tsx
import { VNativeSelect } from "@/components/vui";

<VNativeSelect value={v} onChange={...} className={styles.select}>
  <option value="a">A</option>
</VNativeSelect>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| 原生 select 属性 | value/onChange | 默认不要扩大使用 |

### 反冗余
- 不删除组件；不在 product routes 扩大消费者。

---

## VStringSelect

### 功能
以 string 为 value 的选择封装，减少 key 样板，表单/配置/过滤首选。

### 适用范围
- **适用**：配置项枚举、过滤器、轻量表单 select。
- **不适用**：非 string key / 需 description → `VSelect`。

| 场景 | 选择 |
| --- | --- |
| 状态过滤 | `VStringSelect` |
| 复杂选项描述 | `VSelect` |

### 使用方式
```tsx
import { VStringSelect } from "@/components/vui";

<VStringSelect
  value={status}
  onValueChange={setStatus}
  options={[
    { value: "all", label: "全部" },
    { value: "open", label: "打开" },
  ]}
/>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| value / onValueChange | string 受控 | 过滤器常用 |
| options | `{ value, label }[]` | 空 value 表示「未选」时写清 |

### 反冗余
- 不要再做 `VEnumSelect`；扩展本组件。

---

## VCheckbox

### 功能
复选框：布尔开关与批量选择项。控件本体只有一层描边；无文字时不额外渲染按钮式外框。

### 适用范围
- **适用**：表单布尔、列表多选行。
- **不适用**：互斥单选组 → `VStringSelect` / radio 方案（若后续补 `VRadio`）。

| 场景 | 选择 |
| --- | --- |
| 同意 / 启用 | `VCheckbox` |
| 枚举单选 | `VStringSelect` |

### 使用方式
```tsx
import { VCheckbox } from "@/components/vui";

<VCheckbox isSelected={on} onChange={setOn}>启用</VCheckbox>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| isSelected / onChange | 受控布尔 | 与 label 关联；无 children 时必须提供 aria-label |

### 实现落点
- `forms/VCheckbox.tsx` → `ShadcnCheckbox`

---

## VFieldRow

### 功能
标签 + 控件 + 可选说明的表单行布局，统一设置页字段结构。

### 适用范围
- **适用**：设置表单每一行。
- **不适用**：超自定义网格布局（可例外手写 grid，但控件仍用 V*）。

| 场景 | 选择 |
| --- | --- |
| 设置字段 | `VFieldRow` + 控件 |
| 工具条内联输入 | 可无 FieldRow |

### 使用方式
```tsx
import { VFieldRow, VInput } from "@/components/vui";

<VFieldRow label="API Key" description="仅本地保存">
  <VInput type="password" value={key} onChange={...} />
</VFieldRow>
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| label / description | 标签与帮助 | 错误放 description 旁或下方 |
| children | 控件 | 必须是 V* 控件 |

### 非职责
- 不做整表校验引擎。

### 反冗余
- 禁止 route 复制 `label > span + input` 而不用 FieldRow（超自定义网格除外）。
