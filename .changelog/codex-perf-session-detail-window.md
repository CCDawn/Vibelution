# perf(session): reuse projected turn items across detail reads

## 现象

一个 35.9 MB journal 的会话，`GET /api/sessions/{id}` 服务端要 2.5 秒（热缓存 0.94 秒），
返回 176 条消息 10.43 MB，其中 `turnItems` 占 97%。逐段测量：读 journal 0.09 秒、
序列化 0.07 秒，其余全部花在投影。

## 根因

`_SessionJournalProjection` 每次 detail 请求都从头 fold 全部活跃事件，并为每个 turn
重新投影 turn items；它的类注释明确写着 "never retained across detail requests"。
同一次读取内按 turn 复用，跨请求不复用，所以每次打开会话都重算一遍。

## 改动

`for_turn` 现在按 `(session_id, journal signature, turn_id)` 复用投影结果：

- signature 来自既有的 `session_conversation_events_signature`，包含文件路径、
  latest sequence、mtime、size——任何 append 都会让它变化，缓存项不会比它来源的
  文件活得更久。
- 进缓存和出缓存都做深拷贝，因为调用方会把 message metadata 合并进拿到的 items。
- 缓存有界（4096 项），按访问顺序淘汰。

## 验证

同一会话三次读取：冷 2.645 s → 热 0.231 s、0.250 s，payload 与消息数完全一致
（10.42 MB / 176 条）。`tests/test_session_detail_contract.py` 47 项通过。

## 未做

payload 体积本身没有变化，`turnItems` 仍是 10.43 MB 的绝大部分；下一步的按需加载
（reasoning / tool 输出折叠拉取）不在本次提交内。
