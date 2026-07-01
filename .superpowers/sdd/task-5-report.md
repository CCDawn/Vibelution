## 改动摘要

- 将 self-observation 的执行从最小本地占位报告改为真实复用现有 session/conversation 边界。
- 新增 `_run_observation_session` 适配层：创建隐藏会话、以 `message_source="self_observation"` 提交消息、轮询 completion snapshot、收集 assistant 输出、生成最终 report。
- observation snapshot 现在会回写 `conversationSessionId`、`messages`、`report`，并把 `latestMessage` 对齐到最后一段 assistant 输出。
- 保持 operator terminate 语义：terminate 后会尝试请求停止底层 session turn，但 worker 不会把状态覆盖回 `done/failed`。
- 在 `session_service` 为 `self_observation` 增加最小零工具约束：`disable_tools=True`。

## 文件

- `core/web/services/self_evolution_control_service.py`
- `core/web/services/session_service.py`
- `tests/test_self_evolution_control_service.py`
- `tests/test_web_session_routes.py`

## 验证命令和结果

- `C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py::test_self_observation_turn_finishes_with_report -q`
  - 结果：PASS（先前红灯为 `_run_observation_session` 缺失，补实现后转绿）
- `C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests\test_self_evolution_control_service.py -k "self_observation" -q`
  - 结果：PASS（27 passed, 49 deselected）
- `C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests\test_web_session_routes.py::test_supervised_agent_session_is_hidden_and_preserves_prompt_with_mental_override tests\test_web_session_routes.py::test_self_observation_message_source_disables_tools -q`
  - 结果：PASS（2 passed）

## concerns

- 当前 observation 复用了隐藏 supervised session 创建入口，但真正的 turn mode 仍走普通 conversation chain；零工具是通过 `message_source=self_observation -> disable_tools=True` 保证的，不依赖独立 provider 直连。
