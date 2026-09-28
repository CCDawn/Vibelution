"""剧本目录：四族 aimock fixture（JSON）+ 程序化备用 runner.mjs。

目录结构（``--fixtures`` 指向本目录）：
- ``fixtures/normal_stream.json``：正常推理流（reasoning + markdown + 多轮）；
- ``fixtures/incident_signatures.json``：历史故障签名（429 / 400 抖动 / 畸形 JSON /
  中途断流 / stall / 格式泄漏）；
- ``fixtures/tool_calls.json``：工具调用（多分片参数 + tool-first 交错）；
- ``fixtures/timing.json``：时序（长思考 / 慢速流）；
- ``runner.mjs``：需要 JS predicate / 动态 response 时的程序化备用入口（当前仅演示）。

路由口径：全部用 userMessage 子串标记路由（每个用例独立标记，跨用例互不串扰）；
sequenceIndex 只用于「首发命中后重试成功」族，且标记用例级唯一，sequence 计数
跨用例残留不构成污染。aimock ``POST /__aimock/reset`` 会清空全部 fixture，禁止
在测试间使用（见 aimock_runtime.py 模块注释）。
"""
