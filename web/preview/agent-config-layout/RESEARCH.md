# 降低 Agent 模型配置成本

目标：普通用户不用理解全部槽位、策略 ID 与压缩参数，也能选择并保存一个可用模型。当前成果为第三版隔离预览，不是正式接入或运行验收。

## 对照证据

| 项目 | 核对来源 | 借鉴部分 | 本项目边界 |
| --- | --- | --- | --- |
| OpenCode | 官方 models 文档；本地 b155b15694dbcc6768f11d2f25cc2bdd1f738ab4，packages/app/src/components/dialog-select-model.tsx 的 ModelList | 可见模型、搜索、通道分组；默认模型与按模型支持的变体分开 | 保留 Agent 级绑定；不照搬会话级自由切换与全局继承 |
| Dify | 官方模型供应商文档；本地 fcb380044cd820c501aad70f157460d257e34dfd，model-selector/model-search.ts 的 modelSupportsScopeFeatures | 通道凭据集中管理；按工具调用和图像需求筛选 | 只参考交互和能力门，不复制源码或增加依赖；registry license 为 NOASSERTION |
| LibreChat | 官方 Model Specs 与 Agents 文档 | 以预设简化选择，provider-specific 参数按需配置 | 复用已有创建预设，不新增未经验证的任务质量/成本模型排名 |

官方链接：
- https://docs.opencode.ai/docs/models/
- https://docs.dify.ai/zh/cloud/use-dify/workspace/model-providers
- https://www.librechat.ai/docs/configuration/librechat_yaml/object_structure/model_specs
- https://www.librechat.ai/docs/features/agents

官方文档本轮在线读取；本地源码为固定版本参考，不代表当前上游 HEAD，也没有运行这些外部产品。

## 已有本地能力

- AgentModelChoice 包含凭据、可用性、通道健康、槽位兼容性、图像和思考强度及来源；AgentModelPicker 已有禁用原因。
- agentCreateContract 已有推荐配置、代码开发、研究协作三个预设及确定性的可用默认模型规则。
- 核心配置已有版本冲突保护和 Agent PATCH；effectiveConfiguration 包含来源与就绪状态。正式保存后需刷新该投影再报告配置回读，不以 PATCH 成功当运行验收。
- 可选槽位未单独绑定时保持现有默认规则；本轮不承诺所有槽位持续跟随主模型。上下文全局值仍是保存时快照。

## 第三版交互

- 默认模型页：主模型与思考方式两项决定，首屏不展开六个并行配置标签。
- 选择器可搜索，显示兼容/凭据失败原因；能力取独立示例元数据，不能用凭据就绪推导工具调用支持。
- 模型思考选项按所选模型变化；不支持原选项时展示重置为默认的待保存说明。
- 五个专用槽位折叠，保持默认；设置例外时明确当前绑定，可恢复默认。
- 保存前显示对象和字段差异；模型保存仅修改模型字段，其他配置草稿保留。其他配置不重复编辑或提交模型字段。
- 其他 Agent 配置仍可访问，保留真实 DTO、权限和各自保存边界。
- 检查仅为静态示例检查，不做模型调用，不代表连通性或真实运行成功。

## 尚未实现

正式页面改造、真实候选 DTO 接入、模型探测/费用提示、保存后有效配置回读和运行生效验证，均等待布局批准后的正式实施。没有引入智能推荐服务、自动模型路由、额度自动回退或新的全局继承协议。
