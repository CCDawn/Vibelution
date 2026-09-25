# 设置面对齐波次 1 —— 隔离预览（settings-align）

对齐 ZCode 设置面的三个决策的**隔离预览**：VSettingsRow 行原语、控件升级、保存模型澄清。
只做预览，不改任何生产代码；预览获用户批准后由后续任务集成。结构照 `ad140abb5`
（shortcuts-settings 预览 harness）的先例：自有 vite config + tsconfig + Tailwind 入口，
不进生产构建/路由/vitest 扫描。

## 三个对齐点

- **A 行原语（查看态）**：`src/VSettingsRow.tsx` 本地复刻 ZCode `SettingsRow` 布局
  （label+说明左、只读值右、行间 border-t、组=圆角边框卡无阴影）。顶部「行列表/卡片流」
  密度开关可 A/B 对比新密度与现状密度。
- **B 控件升级（编辑态）**：json 实时校验（红边+行内错误+首个解析错误行列定位，合法显示
  「✓ 格式正确」，不再静默存原始串）；number 步进器（−/+ 按钮+min/max 硬校验+单位后缀）；
  string_list 逐行校验（非法行行号报错+重复项判非法+行数统计）；布尔/下拉保持
  VCheckbox/VStringSelect。
- **C 保存模型**：字段级声明双轨——布尔/下拉=即时类（改后直接提交，徽标「已生效」），
  文本/数字/列表/json=草稿类（改后徽标「待保存」，显式保存才提交）。顶部常驻保存条
  （待保存 N 项；N=0 或有非法草稿时禁用保存）。有草稿时「离开页面（模拟）」触发三选一
  VUI 确认弹窗（保存并离开/放弃并离开/留下）。保存/放弃后全部徽标清除。

## 数据真实性

字段名/默认值照真实配置编写：分区取 `core/web/services/config_editor_schema.py` 的
EDITOR_SECTION_SPECS（`context-compression`），字段取 `config/models.py`
ContextCompressionConfig（enabled/micro_compact_enabled/compression_model/max_token_limit/
summary_max_chars/micro_compact_tool_whitelist/summary_chars），白名单默认值与
MICRO_COMPACT_DEFAULT_TOOL_WHITELIST 一致。不连后端；compression_model 的下拉选项为
演示用样例（生产中是自由文本字段）。

注意：预览的 list 校验以工具注册名格式为真实样例（任务书中「URL 列表」同型，仅校验
pattern 不同）；「保存」是模拟动作，真实集成走 previewConfigDraft → apply 管线 +
字段级即时声明。

## 运行

```bash
cd web
npx tsc -p preview/settings-align/tsconfig.json --pretty false   # 预览类型检查
node preview/settings-align/scripts/logic-selftest.mjs           # 纯逻辑自检（36 断言）
python preview/settings-align/scripts/capture_screens.py         # 起 5187 截图+交互断言
```

## 确定态深链

服务根为 `http://127.0.0.1:5187`，页面路径 `/preview/settings-align/index.html`：

| state | 内容 |
| --- | --- |
| `?state=view-rows` | 查看态·行列表（新密度，默认） |
| `?state=view-cards` | 查看态·卡片流（现状密度对比） |
| `?state=edit-clean` | 编辑态·干净（无变更，保存禁用） |
| `?state=edit-dirty` | 编辑态·脏（即时字段「已生效」+草稿字段「待保存」+保存条计数 1） |
| `?state=json-error` | json 非法（尾逗号）→ 红边+错误行列定位 |
| `?state=list-invalid` | 白名单两行非法 → 行号报错+统计 |
| `?state=saved` | 保存完成 → 徽标清除+toast「已保存到外部配置」 |

可选 `&theme=dark` 切暗色；`中/EN` 切双语。

## 截图

`screenshots/`（gitignore，不入库）由 capture 脚本产出 7 张 state 截图；
`capture-report.json`（入库）记录断言与 console/pageerror 收集，任何 console error
都会让脚本非零退出。

## 边界

- VSettingsRow 是预览本地组件；正式 designs 登记与 `vuiComponentDesignContract` 接入留给集成任务。
- 预览根节点带 `data-vui-app="preview"`（对齐生产 AppShell 的原生控件 CSS 作用域），
  宽 textarea 以内联 `height:auto` 抵消 `vuiFormControlClass` 的固定高度类。
- 纯样式只用 `--vui-*` 令牌与 token 工具类（错误色 `var(--state-error)`），无裸色值。
