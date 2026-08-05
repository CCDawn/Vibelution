# 按钮选型（Agent 硬规则）

**读者：coding Agent。** 产品 UI 只允许下列按钮门面，禁止第三套。

权威设计正文：`web/src/components/vui/designs/primitives/actions.md`
红线：`AGENTS.md` §2 · `development-standard.md` §9.1

---

## 决策表（先匹配再写）

| 场景 | 用 | 不用 |
| --- | --- | --- |
| 主 CTA、表单提交、对话框确认/取消、工具条标准动作 | **`VButton`** | 裸 `<button>`、VNative（除非密表行内） |
| 仅图标（刷新/关闭/更多） | **`VIconButton`** | 空 label 的 VButton |
| 站内导航且要 link 语义 | **`VRouteLinkButton`** | `onPress`+`navigate` 冒充 link |
| 画布节点、kanban 热区、超密列表行、多行卡片整卡点击 | **`VNativeButton`** | VButton（浮层/slot 过重） |
| SVG 内部几何命中（极少） | **documented exception** + 自有 class；优先仍试 `VNativeButton` | 无注释的裸 `<button>` 复制成通用模式 |

---

## 硬禁止

```text
[ ] @heroui/react
[ ] routes 直连 renderers/shadcn/*
[ ] 新建 PrimaryButton / AppButton / 第三 button 门面
[ ] 用户可见 UI 交付非 VUI 路径
```

---

## 同页混用规则

- **允许**：工具条 `VButton` + 列表行 `VNativeButton`
- **禁止**：同一语义动作两个实现（例如「保存」一处 V 一处 native）
- 新代码优先 **VButton**；仅当设计说明「何时使用 VNative」命中时用 native

---

## 实现落点

| API | 文件 |
| --- | --- |
| `VButton` | `web/src/components/vui/primitives/VButton.tsx` |
| `VIconButton` | `web/src/components/vui/primitives/VIconButton.tsx` |
| `VNativeButton` | `web/src/components/vui/primitives/VNativeButton.tsx` |
| `VRouteLinkButton` | `web/src/components/vui` export |

---

## 页面壳 recipe 标记（大路由）

完整迁到 `V*Page` 组件不是一天的事；**最低合同**是入口带稳定标记 + layout id：

| 路由 | 最低标记 | 布局 id / recipe 实现 |
| --- | --- | --- |
| Chat | `data-vui-recipe="chat-session-workbench"` | `WORKBENCH_LAYOUT_IDS.chat` |
| Agents | `data-vui-recipe="agents-management-workbench"` | `AgentWorkspaceLayoutPanel` → `VListDetailPage` + `WORKBENCH_LAYOUT_IDS.agents` |
| Teams | 薄 re-export `teams/TeamsRouteWorkbench` | `VBoardWorkbenchPage` / `VCanvasWorkbenchPage` + `WORKBENCH_LAYOUT_IDS.teams` |
| Git/Logs/… | 优先 `VDenseOpsPage` 等 | 见各 `*Route.tsx` |

门禁：`web/src/components/vui/vuiShadcnRouteContract.test.ts`
- routes **禁止**裸 `<button>`
- 上表标记缺失 fail

## 自检

```text
1. 是否已有 designs/primitives/actions.md 覆盖？
2. 是否 routes 只 import components/vui？
3. 画布/密表是否误用了带浮层 VButton？
4. 主 CTA 是否误用了 VNative 导致主次不分？
5. routes 内是否还有裸 <button>？
6. 大路由是否有 data-vui-recipe + layout id？
```
