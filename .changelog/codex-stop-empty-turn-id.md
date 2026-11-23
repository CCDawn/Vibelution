---
kind: fix
area: web
---

停止请求接受空 turnId：composer 在乐观层还没有真实 turn id 时会发送 turnId=""，
原先 min_length=1 的校验把这条请求直接 422 拒掉，导致刚发送时点停止完全无效。
