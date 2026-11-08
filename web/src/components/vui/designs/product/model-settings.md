# 模型配置工作区

## ConfigProviderRegistryPanel

### 功能
在同一模型服务页面选择厂商，切换模型目录与连接设置。搜索仅改变导航可见项，保持当前编辑对象与草稿。未启用项可展开，订阅授权使用既有独立连接面。

### 适用范围
设置中的模型服务；继续保留 `model-connection` 深链、原凭据与配置 API，不改变模型执行与 Launcher 边界。

### 使用方式
通过 VListDetailPage 与 WORKBENCH_LAYOUT_IDS.configModelAssets 复用已有分栏宽度记忆。宽屏显示厂商导航与当前内容，窄屏逐层进入并有返回入口。连接凭据、路由预览和即时启停继续使用已有安全回调。高级协议、诊断与删除放在明确的高级管理入口。

## ProviderModelsTab

### 功能
搜索和筛选模型、发现及添加模型、选择单模型编辑。生产页面使用列表与单模型编辑逐层切换；目录筛选隐藏当前对象时明确提示，禁止悄悄切换对象。

### 适用范围
厂商下的模型目录；检测、图像与推理能力探测保留各自真实含义，不用获取目录成功冒充真实推理或工具可用。

### 使用方式
复用 VEntityList、VButton、VStateSurface。列表只负责选择与扫描；生成参数优先编辑，能力与验证证据次要展开。参数只能使用 modelEditableFields 白名单，协议与凭据不可编辑。

## ConfigModelEntryEditor

### 功能
受控单模型表单，显示模型身份、上下文窗口和必要开关；生成参数继承默认值，按需添加覆盖。非法输入保留并阻止统一保存。

### 适用范围
已添加的模型。编辑数据按 modelRef 由 ConfigRoute 持有，跨厂商、模型、内容分类及关闭编辑面均保留，不落浏览器持久存储。

### 使用方式
使用 VInput、VStringSelect、VSwitch 和 VButton。统一保存将原始编辑通过 foldModelEditorDrafts 和 applyModelEntryEdits 合并到现有配置 apply 请求；保留未知配置、能力和协议字段。失败保留草稿，放弃更改仍走原确认及重新加载链路。兼容嵌入可选择提供 onSave，但生产工作区只使用页面保存入口。

## ConfigDecisionModelsPanel

### 功能
模型用途中的决策与交接模型摘要列表，点击单项编辑；默认不展开所有模型字段。保留新增、移除、探测、启停和交接功能。

### 适用范围
现有 decision_models 与 decision_handoff_model_id，不新增普通聊天或助理的全局模型策略。

### 使用方式
复用 VDialog、VSection 与现有表单组件。分类切换保持组件挂载，按 entity 保留草稿；有效文本字段在失焦或关闭时提交页面草稿。未完整或尚未被父页面接收的输入通过 onPendingChange 参与页面未保存状态、保存阻止和离开确认；显式放弃并重新加载时重建编辑器。即时启停及交接保留既有单项写入与并发合并规则。探测结果绑定探测时的模型身份，不能沿用旧模型结果。
