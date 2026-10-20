# 股票 Agent 排版修复预览

用户已确认此隔离预览，布局已落实至正式 Finance 页面。入口：`/preview/finance-ui-repair/index.html`。

- 保留全部 15 个功能入口，用准确页面标题与当前股票提示位置。
- 股票研究首屏直接选择对象、日期、范围和深度；执行过程、引用资料与报告可互相定位。
- 财报资料使用列表与阅读区；属性折叠，保留原文及页码入口。
- 短内容按内容高度排列；复杂表单区分主要设置、高级设置和结果。
- 低于 1440px 时对话从常驻栏转为按需打开；低于 900px 时导航改为对话框。
- 页面状态可在顶部切换，全部来自确定性演示数据，不运行模型、不创建真实研究或订单。

`NumericAcceptance.tsx` 复用正式持仓和行情组件，仅注入本地报价 fixture，用来检查数值列修复；刷新仍返回本地 fixture。

从仓库根启动：

```text
node web/node_modules/vite/bin/vite.js --config web/preview/finance-ui-repair/vite.config.ts --host 127.0.0.1 --port 5198
```

类型检查：

```text
node web/node_modules/typescript/bin/tsc -p web/preview/finance-ui-repair/tsconfig.json --pretty false
```

正式实现保留原生会话、模型检查、资料权限及交易行为；除数值列宽与换行外，已落实导航、新建研究、资料阅读、技能学习及交易/回测表单布局。正式资料正文仍由用户主动展开后读取；窄屏导航和对话按需占据阅读区，保持同一原生对话挂载。此预览继续使用演示数据，不能替代正式运行验收。
