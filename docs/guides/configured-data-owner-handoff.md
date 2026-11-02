# 已配置历史数据的 owner 接管

本入口用于项目目录已经迁移、operator 配置仍指向同一项目历史数据的情况。先确认数据归属，再由可信本地 operator 审阅计划并明确批准 apply。用户确认“这是同一项目的数据”只提供归属事实，不替代对具体写入计划的批准。

实现 owner 是 `core/infrastructure/storage_owner_handoff.py`，唯一写入口是 `scripts/project_storage_owner.py`。助理模型和 HTTP API 没有此接管写入口；知识目录只消费有效证明，并继续执行原有 operator 授权、ACL 和来源检查。

## 作用与限制

接管只在当前 instance 下新增 `storage-owner-handoff.json` 和对应锁文件。它把当前项目物理身份与配置中已经选定的历史 data/workspace、旧迁移 marker 绑定起来，允许知识目录读取已有 metadata。它不复制或移动数据，不修改 operator 配置、旧 marker 或当前迁移 marker，也不初始化旧数据目录。

这份证明不表示全量存储清单、内容完整性、迁移就绪、无活动写入者或全平台健康已经通过验收。真实知识读取仍需在后台加载新代码后单独验证。当前 canonical migration marker 一旦存在，知识入口仍服从该权威，不用接管证明覆盖或绕过它。

## 先生成只读计划

在已验证的 checkout 中调用 CLI，并显式传入实际产品项目根目录，避免把任务 worktree 当作要接管的项目：

```powershell
python -X utf8 scripts/project_storage_owner.py plan --project-root "<实际项目根目录>"
```

`plan` 不创建目录、记录或锁。应审阅以下字段：

| 字段 | 必须核对的事实 |
| --- | --- |
| `binding.projectRoot` / `projectId` / `instanceId` | 当前产品项目及其物理目录身份 |
| `binding.sourceProjectRoot` / `sourceInstanceId` | 用户确认归属的旧项目与历史 instance |
| `binding.sourceDataRoot` / `workspace` | operator 配置当前选中的同一项目数据 |
| `binding.sourceMarkerSha256` | 已完成旧迁移 marker 的精确内容摘要 |
| `recordPath` / `writes` | 本次唯一新增的接管记录及锁文件 |
| `planDigest` / `expectedRecord` | 本次批准绑定的计划摘要，以及记录尚不存在 |

目录、配置路由、项目身份或 marker 变化会使旧摘要失效。路径大小写、斜杠、环境变量表达等价且仍指向同一物理 owner 时，证明保持有效；换到另一 instance、目录替换、reparse 或 hardlink 别名会拒绝。

## 批准后一次 apply

用户批准具体计划后，保留一个稳定的 request ID，使用计划原有摘要：

```powershell
python -X utf8 scripts/project_storage_owner.py apply --project-root "<实际项目根目录>" --plan-digest "<批准的 planDigest>" --confirm-relocated-data --request-id "<稳定的 apply request ID>"
```

写锁内会重新校验完整绑定。`plan_changed` 表示现场已经变化，应重新生成并审阅计划，不能自行换摘要继续。已有记录不会被覆盖；同一请求可读取原回执，不应换 request ID 重试来制造第二次决定。

如果响应丢失，先只读查询原请求：

```powershell
python -X utf8 scripts/project_storage_owner.py receipt --project-root "<实际项目根目录>" --request-id "<原 apply request ID>"
```

`receipt` 不创建目录或锁；它证明历史请求是否已经提交，并返回记录当前为 active 或 revoked 的状态。历史回执成功不等于当前数据可读，也不替代 live binding 检查或知识读取验收。

## 回退与验收

回退使用当前回执中的 `currentRecordDigest`，以新的稳定 request ID 撤销证明：

```powershell
python -X utf8 scripts/project_storage_owner.py revoke --project-root "<实际项目根目录>" --record-digest "<当前 currentRecordDigest>" --request-id "<稳定的 revoke request ID>"
```

撤销保留原绑定、apply/revoke 回执和全部数据。CAS 摘要不符时停止，不覆盖后来变化；响应丢失仍只查询原 revoke request ID。已撤销记录不会被新的 apply 自动替换。

实际验收需核对记录绑定正确、旧 marker 与配置未被修改、后台使用的项目和数据路由正确，再通过原助理 Session 的知识目录读取验证。失败时保留准确错误及原请求回执，不把证明存在解释为全平台已托管。
