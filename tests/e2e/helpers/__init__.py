"""Playwright e2e 手动车道的辅助模块（真实分支实例生命周期 + CDP + 前端构建）。

仅在被 pytest 收集且设置 ``VIBELUTION_E2E=1`` 时由 conftest 使用；
默认/serial 车道因模块级环境门只会 skip，不会触发任何进程操作。
"""
