# A股桌面智能体：功能左栏、中间详情、右侧会话预览

用户已确认布局方向，当前是具体界面的隔离预览，正式 finance route 尚未修改。

- 左栏复用正式 `FINANCE_WORKSPACE_GROUPS` 的 15 个功能入口；底部固定当前助手与独立模型入口。
- 顶部用 VTabs 切换原生会话的示例投影；新建、全部会话、当前会话菜单集中在标签行。
- 中间显示完整研究报告、财务核对、行情图表与回测等详细内容；右侧固定完整对话与输入框，可调整宽度与收起。
- 每会话保存草稿、对话滚动位置、选中的详情与各详情阅读位置。顶部切换会话时中间与右侧同步恢复；从详情追问可重新展开会话栏。
- 标签关闭不会删除会话，全部会话提供搜索、归档恢复、删除确认与批量管理。详情使用 VDialog 放大；栏宽变化后活动会话标签自动定位。
- 可用桌面区域不足 1080px 时，功能导航收进 VDialog，保持详情与会话可见。取消原先的页面最小宽度限制，避免内置浏览器侧面板截断右侧。
- 只用 VUI 产品 API、正式 recipe、共享 pane persistence。没有新增公共 VUI 组件或改写全局设计 token。

URL：`http://127.0.0.1:5187/preview/finance-desktop-tabs/index.html`

启动：在 web 中用现有 Node 运行 `node_modules/vite/bin/vite.js --config preview/finance-desktop-tabs/vite.config.ts`。

预览使用确定性 A股示例，不读取生产凭据、不调用模型、不连接真实行情、报告或交易接口。Vite proxy 已关闭；会话与模型只保存在此独立 origin 的 `finance-desktop-tabs-preview.v1`。默认模型文案为 Qwen3.8 Flash；备用选项仅为布局样例。正式实现复用原生会话权威、现有助手模型保存及可用性校验。

目标桌面视口：1280×720、1920×1080，以及当前内置浏览器的较窄桌面工作区；不包含手机版。

已通过预览 TypeScript、工作台 TypeScript 和两个 VUI 契约。上一版已检查新会话、关闭标签找回、会话管理与模型示例设置；本版重新实际检查全部工具在中间打开、右侧对话与输入框完整显示、跨会话草稿和详情恢复、两边阅读位置恢复、从详情追问展开右栏、窄工作区导航菜单、底部可见性及页面无横向溢出。删除最终执行和真实服务调用不计入本轮预览验收。

截图与操作证据：`C:/Users/Administrator/AppData/Local/Temp/vibelution-finance-desktop-tabs-20261013`。
