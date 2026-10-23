# 团队工作台紧凑布局交互预览

本目录是独立预览入口，未被正式路由引用。只使用当前页面内的模拟数据，不连接真实团队、Agent、模型或保存接口。

## 预览方向

全局导航 40px，工作区标题栏 52px；侧栏团队标题、流程标题和节点配置标题顶边对齐。移除常驻副标题及面板外层留白，使用现有 VUI 产品 API、VCanvasWorkbenchPage、WORKBENCH_LAYOUT_IDS.teams 和共享面板尺寸持久化。

空白页直接展示资料调研与交叉验证、文档审查模板，以及空白创建入口；没有流程时不显示已保存、模式切换、保存或试运行。编辑页保留流程列表、按顺序连接的节点和右侧配置，选中节点可编辑名称、负责人及要求。模拟成员为六位；模板、字段与运行行为沿用原预览。

## 打开与启动

在 web 目录运行 node node_modules/vite/bin/vite.js --config preview/generic-team-workspace/vite.config.ts。默认仅监听 127.0.0.1:5237；端口占用时以 --port 指定本任务独立端口。后台进程必须隐藏窗口。

入口：/preview/generic-team-workspace/index.html?scene=empty 打开空白页；?scene=edit 打开编辑页。右上角“空白页 / 编辑页”可随时切换。类型检查：node node_modules/typescript/bin/tsc -p preview/generic-team-workspace/tsconfig.json --noEmit。缓存与构建产物放在系统临时目录 vibelution-compact-team-preview。

## 已覆盖与边界

浏览器检查覆盖 1440×900、1024×768、390×844 下的空白页和编辑页，模板创建、节点名称/要求编辑、保存反馈、必填校验与窄屏配置抽屉。窄屏无文档横向溢出。

数据只保留在本页，刷新后重置；“保存”、执行推进、人工确认、失败重试、停止和产物内容均为前端模拟。本轮重点检查空白与编辑体验，未验收真实执行链路。Vite 预览服务器拒绝 /api/ 请求。正式 UI 与后端没有修改；此预览待用户反馈后再决定正式实现。
