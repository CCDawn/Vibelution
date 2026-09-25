# Settings Rows（设置面行原语）

## 选型总表（防冗余）

| 需求 | 使用 |
| --- | --- |
| 设置页结构化字段的行布局（label+说明左、定宽控件右） | `VSettingsRow` |
| 设置页一组行的圆角边框卡容器 | `VSettingsGroupCard` |
| 表单里标签在上/在前的普通字段行 | `VFieldRow`（forms/controls.md） |

行原语与 `VFieldRow` 是两种形态：行原语是**水平两列、定宽控件列**的设置面密度；
`VFieldRow` 是普通表单的标签+控件组合。不要用 `VFieldRow` 拼设置行，也不要给
`VSettingsRow` 加普通表单职责。

---

## VSettingsRow

### 功能

ZCode SettingsRow 对齐的设置行布局壳：左侧 label（`--vui-font-sm` 加重）+ 一行
说明（xs 弱色）；右侧**定宽控件列**；行间 `border-t`（`--vui-border-subtle`）分隔。
行右侧可挂状态徽标（`status`，clean 时不渲染）。本组件只做布局，不含校验、
保存逻辑或第二套控件。

**密度语义**：设置面结构化字段的标准密度。查看态右列放只读值或即时类活控件
（布尔/下拉），编辑态放对应控件；宽编辑器（json/list 文本域、说明性错误列表）
放 `footer`，占满组卡宽度。

**变体表**：

| 变体 | Prop | 布局 |
| --- | --- | --- |
| 默认 | `controlLayout="default"` | 右列 192px；`detail` 换行渲染在行下方 |
| 宽控件 | `controlLayout="wide"` | 右列 280px；`detail` 并列在控件左侧 |
| 状态徽标 | `status` | 渲染在控件列最左（已生效/待保存/失败等） |
| 宽编辑器 | `footer` | 整行下方独立块（json/list 编辑器、错误列表） |

### 适用范围

- **适用**：设置/偏好页的结构化字段行（配置工作台、偏好表单），配合
  `VSettingsGroupCard` 作为组容器。
- **不适用**：普通创建表单（`VFieldRow`）；密集表格（`VDenseTable`）；
  画布/工具条。

### 使用方式

```tsx
import { VSettingsGroupCard, VSettingsRow, VCheckbox } from "@/components/vui";

<VSettingsGroupCard>
  <VSettingsRow
    label="启用上下文压缩"
    description="上下文接近上限时自动压缩较早内容。"
    control={<VCheckbox isSelected={enabled} onChange={setEnabled} aria-label="启用上下文压缩" />}
    status={changed ? <VChip tone="accent">已生效</VChip> : null}
  />
  <VSettingsRow
    label="压缩触发阈值"
    description="上下文超过该值触发全量压缩。"
    controlLayout="wide"
    control={<NumberStepper />}
  />
  <VSettingsRow
    label="各级摘要字数"
    description="light/standard/deep/emergency 四级各自的字数上限。"
    control={<span className="text-vui-xs text-vui-fg-secondary">4 个层级</span>}
    footer={<JsonEditor />}
  />
</VSettingsGroupCard>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| label / description | 左列文案 | description 只放一行说明，长 hint 用 title |
| control | 右列控件 | 查看态=只读值/即时活控件；编辑态=控件 |
| status | 行徽标 | 语义色：品牌色=已生效，中性=待保存，错误色=失败 |
| controlLayout | 列宽变体 | number 步进器等宽控件用 `wide`（280px） |
| footer / detail | 行下/行内附属 | 宽编辑器一律放 `footer`，不塞进控件列 |
| testId | 测试定位 | 约定 `row-<fieldPath>` |

### 非职责

- 不做字段校验、保存状态机或目录级聚合；这些属于路由/配置模型层。
- 不内含任何具体控件；控件由调用方组合。

### 实现落点

- `forms/VSettingsRow.tsx`（纯布局壳，`data-vui="settings-row"`）

---

## VSettingsGroupCard

### 功能

一组设置行的容器：圆角边框卡、无阴影、`overflow-hidden`（首行 `border-t`
由 `VSettingsRow` 的 `first:border-t-0` 吸收）。对照 ZCode SettingsGroupCard。

### 适用范围

- **适用**：设置页同组字段行的容器（一个 tier/一组语义相关字段）。
- **不适用**：普通内容面板（`VPanel` / `VSurface`）；需要阴影的浮层。

### 使用方式

```tsx
<VSettingsGroupCard testId="settings-group">{rows}</VSettingsGroupCard>
```

### 非职责

- 不做分组标题/展开折叠；标题属于页面层（`VSection` 等）。

### 实现落点

- `forms/VSettingsRow.tsx`（`data-vui="settings-group"`）
