# 工具管理布局预览

复用 VWorkbenchFrame + VListDetailPage、公共 VUI 控件和已有灰/白工作台 token。正式路由与真实工具接口均未修改。

两个任务分开显示：工具库提供检索、工具详情、状态与测试；Agent 工具配置提供按工具包浏览、逐项权限、工作区写入边界、追加/替换、验证、草稿与确认保存。批量操作只在主动进入选择并勾选工具后出现。

本预览包含 15 个确定性样例；真实标识来自当前页面与源码，描述已缩短，生成工具为明确标注的示例。风险、权限、计数、参数与连接配置是安全 mock，不能作为运行数据。未收录工具包仍保留入口并显示样例缺口，正式实现须保留完整注册表、原权限规则、深链、服务器预览/确认、测试兼容性结果、image2 模型和搜索依赖的全部状态。

从 web 运行 `node node_modules/vite/bin/vite.js --config preview/tools-management/vite.config.ts`。页面 `/preview/tools-management/index.html`。无后台 proxy、无 API 调用、无模型调用或真实授权变更。

## 正式落地约束

- ToolsRoute 继续持有已有查询/权限草稿/Mutation；不新建权限事实源。
- view 将深链 policy/bundle 对应到 Agent 配置，detail/test 对应工具库；保留 returnTo。
- 同一个常驻 Frame 和现有 WORKBENCH_LAYOUT_IDS.tools 尺寸记忆；每个视图仅替换正文。
- 收到用户明确批准后才能修改正式 ToolsRoute owning surface。
