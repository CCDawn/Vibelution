## Unreleased

- fix: 生效状态按前端、后端、桌面壳三层分层给出，只改文档、测试或版本账本时不再提示需要重启后端。
- feat: 仅前端变更时不必重启后端，即可在校验通过后直接切换到新界面（`POST /runtime/frontend/switch`）。
