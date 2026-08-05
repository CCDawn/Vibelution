# 08 · Git / UI / User

## `[git]`

```toml
[git]
commit_message_model_ref = ""   # 空=默认；可填 model_ref
commit_message_prompt = """..."""  # 提交说明生成提示词，含 {summary}{files}{diff}
```

| 字段 | 说明 |
| --- | --- |
| `commit_message_model_ref` | 用于生成 commit message 的模型引用 |
| `commit_message_prompt` | 提示词模板 |

改后不影响主对话 profile，但会影响 Git 面板生成提交文案的模型调用。

## `[ui]`

UI 偏好（键以当前 schema 为准）。与 VUI 设计系统无关的「用户偏好」放这里；**组件 API 不在此配置**。

前端产品 UI 必须走 VUI（见 `AGENTS.md` 红线），不要用配置绕过设计系统。

## `[user_profile]`

```toml
[user_profile]
avatar_image_path = ""
```

用户级展示资料，非 LLM 协议。

## Agent 清单

- [ ] git 模型 ref 指向有效 provider/model
- [ ] 未在 prompt 中嵌入密钥
- [ ] UI 改动未违反 VUI 红线
