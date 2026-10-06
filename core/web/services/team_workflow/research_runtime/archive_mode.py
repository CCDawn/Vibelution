"""挑战杯封存模式（challenge archive mode）统一开关。

封存语义：挑战杯批次归档后，产品运行时进入"只读可看"状态——

- 不再自动推进 / 改写任何 research workflow 状态（auto-advance、reaper、
  hypothesis recovery 全部停用）；
- 启动时不启动 research workflow 驻留 runtime（outbox pump 的 4 worker +
  maintenance + receipt-persistence + hypothesis-recovery 线程全部不存在）；
- 启动时跳过会为大量 open 会议补写 fence 记录的 meeting-driver 恢复扫描；
- 只读查询路径（投影、UI 查看、既有记录读取）不受影响。

这是全部封存读取处的单一事实源：lifecycle、runtime_factory、outbox_pump、
reaper、automation_policy_executor 都经由本模块判断，禁止各处散读 env。

开关解析优先级（见 :func:`challenge_archive_mode_enabled`）：

1. env ``VIBELUTION_CHALLENGE_ARCHIVE_MODE`` 显式取值（truthy 开 /
   falsy 关，操作员紧急退出的逃逸口，也是复活流程的复核手段）；
2. operator config ``[research] challenge_archive_mode``；
3. 缺省关——不配置时行为与历史版本完全一致。

pytest 下只认 env、不回落 operator config：测试进程可能落在操作员
真机上，若回落读取活配置，用户实例的封存配置会污染测试行为（违反
"默认关零行为差异"硬门）。与
``runtime_factory._compact_hypothesis_round_failures_best_effort``
的 pytest 先例同一隔离纪律。
"""

from __future__ import annotations

import os

#: 总开关 env。truthy = 封存开；falsy 显式关（覆盖 config）；未设置 = 看 config。
CHALLENGE_ARCHIVE_MODE_ENV = "VIBELUTION_CHALLENGE_ARCHIVE_MODE"

_TRUTHY_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSY_VALUES = frozenset({"0", "false", "off", "no"})


def challenge_archive_mode_enabled() -> bool:
    """封存模式是否开启（env 显式值 > operator config > 默认关）。

    任何配置读取失败都 fail-open 到 False（不封存），封存门永远不能
    因为配置故障而意外改变启动行为。
    """

    raw = str(os.environ.get(CHALLENGE_ARCHIVE_MODE_ENV) or "").strip().lower()
    if raw in _TRUTHY_VALUES:
        return True
    if raw in _FALSY_VALUES:
        return False
    return _operator_config_archive_enabled()


def _operator_config_archive_enabled() -> bool:
    """读取 operator config ``[research] challenge_archive_mode``。

    pytest 下恒 False（测试隔离，见模块 docstring）；读取失败 fail-open
    到 False。
    """

    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    try:
        from config.settings import get_config

        return bool(get_config().research.challenge_archive_mode)
    except Exception:  # noqa: BLE001 - 封存门不因配置故障改变行为
        return False
