"""Additive configuration actions require an explicit grant upgrade."""
from .agent_configuration_contracts import AgentParametersUpdate
from .configuration_discovery_contracts import AgentPromptUpdate

CONFIGURATION_ACTION_MODELS = {"agent_parameters_update": AgentParametersUpdate, "agent_prompt_update": AgentPromptUpdate}
CONFIGURATION_ACTION_SCOPES = {name: "agents:configuration:write" for name in CONFIGURATION_ACTION_MODELS}
CONFIGURATION_ACTION_HELP = {
    "agent_parameters_update": "经原生审批修改单Agent的model、budget或compression一类参数；先agent_config_get读取当前版本、限制和来源，携原configRevision。一次只改一个block，不宣称跨类别原子事务。保存后重读agent_config_get核对stored/effective；空reasoning恢复默认，budget null清覆盖、0无限，context不支持伪装reset。",
    "agent_prompt_update": "经原生审批修改单Agent角色提示词；先agent_prompt_get读取configRevision/templateId/contentHash，原样携CAS。内容上限8000字符且请求总计16000bytes；复制为独立inline模板再绑定，不修改共享模板或COMMON/SOUL，不影响其他Agent。从下一次新提交生效；未知回执仅查原request_id不重放。",
}
