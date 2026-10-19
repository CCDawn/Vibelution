# 股票 Agent 排版修复预览

隔离预览，等待用户确认布局后再进入正式页面。入口：`/preview/finance-ui-repair/index.html`。

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

正式代码本轮只修复持仓、行情与总览中的数值列宽和换行，不改变数值计算、单位或交易行为。
