#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1-f 工具结果 resultBudget 测试。

覆盖：
- 预算描述符：声明命中 / 缺省逐字节等价
- artifact 档：落盘 + sha256 + 引用 + 预览 + 恢复
- 落盘失败静默回退截断档（成功调用不变失败）
- 截断档统一结构化后缀（original_chars/model_chars/strategy，head/tail）
- 空输出占位泛化（shell 既有标记原样保留）
- read-only 并行批下 artifact 落盘按 tool_call_id 隔离
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from langchain_core.messages import ToolMessage

from core.infrastructure.tool_result import (
    EMPTY_TOOL_OUTPUT_PLACEHOLDER,
    package_tool_result_facts,
    render_tool_result_for_model,
)
from core.infrastructure.tool_result_artifact import (
    TOOL_RESULT_ARTIFACT_DIR_ENV,
    build_tool_result_artifact_ref,
    compute_tool_result_digest,
    read_tool_result_artifact,
)
from core.infrastructure.tool_result_budget import (
    MIN_MODEL_CHARS,
    PREVIEW_TAIL,
    STRATEGY_ARTIFACT,
    STRATEGY_TRUNCATE,
    ToolResultBudget,
    ToolResultBudgetOutcome,
    apply_tool_result_budget,
    clear_tool_result_budgets,
    register_tool_result_budget,
    serialize_tool_result,
)
from core.orchestration.tool_lifecycle import ToolLifecycleBridge

SHELL_EMPTY_MARKER = "[命令执行完成，无输出]"


def _result_section(tool_message_content: str) -> str:
    """提取事实块 Result 段（预算约束的主体，不含事实头协议开销）。"""
    marker = "\nResult:\n"
    if marker not in tool_message_content:
        return tool_message_content
    return tool_message_content.split(marker, 1)[1]


@pytest.fixture(autouse=True)
def _isolated_budget_registry():
    clear_tool_result_budgets()
    yield
    clear_tool_result_budgets()


@pytest.fixture
def artifact_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(TOOL_RESULT_ARTIFACT_DIR_ENV, str(tmp_path / "tool-results"))
    return tmp_path / "tool-results"


def _register(tool_name: str, **kwargs: Any) -> ToolResultBudget:
    budget = ToolResultBudget(**kwargs)
    register_tool_result_budget(tool_name, budget)
    return budget


class TestBudgetDescriptor:
    def test_descriptor_normalizes_bounds_and_strategy(self):
        budget = ToolResultBudget(max_model_chars=1, max_inline_chars=2, strategy="weird", preview="side")
        assert budget.max_model_chars >= MIN_MODEL_CHARS
        assert budget.max_inline_chars >= budget.max_model_chars
        assert budget.strategy == STRATEGY_TRUNCATE
        assert budget.preview == "head"

    def test_packaging_max_chars_follows_declaration(self):
        assert ToolResultBudget(max_model_chars=3000).packaging_max_chars == 3000
        assert ToolResultBudget(max_model_chars=3000, max_inline_chars=9000).packaging_max_chars == 9000

    def test_undeclared_tool_never_budgeted(self):
        result = "x" * 50000
        budgeted, outcome = apply_tool_result_budget(result, tool_name="no_budget_tool")
        assert budgeted is result
        assert outcome is None

    def test_default_path_byte_equivalent_for_undeclared_tool(self):
        """未声明工具的 handle_tool_result 输出与既有打包渲染路径逐字节一致。"""
        bridge = ToolLifecycleBridge(tool_executor_execute=lambda *a, **k: ("ok", None))
        result = {"status": "ok", "output": "y" * 500}
        messages: list = []
        bridge.handle_tool_result({"id": "call-eq", "name": "plain_tool", "args": {}}, result, None, messages)
        expected = render_tool_result_for_model(
            package_tool_result_facts(result, tool_name="plain_tool")
        )
        assert isinstance(messages[0], ToolMessage)
        assert messages[0].content == expected

    def test_declared_under_budget_passthrough_identity(self):
        _register("passthrough_tool", max_model_chars=4000)
        result = "short result"
        budgeted, outcome = apply_tool_result_budget(result, tool_name="passthrough_tool")
        assert budgeted is result
        assert outcome is None

    def test_dict_result_serialization_matches_packaging_convention(self):
        payload = {"b": 1, "a": "中文"}
        assert json.loads(serialize_tool_result(payload)) == payload


class TestTruncateBudget:
    def test_truncate_appends_structured_suffix(self):
        _register("trunc_tool", max_model_chars=1000, strategy=STRATEGY_TRUNCATE)
        content = "A" * 5000
        budgeted, outcome = apply_tool_result_budget(content, tool_name="trunc_tool", tool_call_id="call-1")
        assert isinstance(budgeted, str)
        assert len(budgeted) <= 1000
        assert outcome is not None
        assert outcome.strategy == STRATEGY_TRUNCATE
        assert outcome.original_chars == 5000
        assert outcome.model_chars == 1000
        assert "[工具结果预算] strategy=truncate, original_chars=5000, model_chars=1000" in budgeted
        assert budgeted.endswith(", model_chars=1000")

    def test_truncate_head_keeps_prefix(self):
        _register("head_tool", max_model_chars=500, strategy=STRATEGY_TRUNCATE, preview="head")
        content = "HEAD" + "x" * 2000 + "TAIL"
        budgeted, _ = apply_tool_result_budget(content, tool_name="head_tool")
        assert budgeted.startswith("HEAD")

    def test_truncate_tail_keeps_suffix(self):
        _register("tail_tool", max_model_chars=500, strategy=STRATEGY_TRUNCATE, preview=PREVIEW_TAIL)
        content = "HEAD" + "x" * 2000 + "TAIL"
        budgeted, _ = apply_tool_result_budget(content, tool_name="tail_tool")
        assert "TAIL" in budgeted
        assert not budgeted.startswith("HEAD")

    def test_tiny_budget_still_carries_truncated_suffix(self):
        _register("tiny_tool", max_model_chars=MIN_MODEL_CHARS, strategy=STRATEGY_TRUNCATE)
        budgeted, _ = apply_tool_result_budget("z" * 10000, tool_name="tiny_tool")
        assert "[工具结果预算]" in budgeted
        assert len(budgeted) <= MIN_MODEL_CHARS


class TestArtifactBudget:
    def test_artifact_persists_full_text_with_sha256(self, artifact_dir):
        _register("artifact_tool", max_model_chars=1200, strategy=STRATEGY_ARTIFACT)
        content = "DATA-" + "q" * 6000
        budgeted, outcome = apply_tool_result_budget(
            content, tool_name="artifact_tool", tool_call_id="call-artifact-1"
        )
        assert outcome is not None
        assert outcome.strategy == STRATEGY_ARTIFACT
        assert len(budgeted) <= 1200
        assert outcome.artifact_ref == build_tool_result_artifact_ref("call-artifact-1", outcome.artifact_sha256)
        assert outcome.artifact_sha256 == compute_tool_result_digest(content)
        # 落盘全文可恢复且逐字节一致
        assert outcome.artifact_path
        restored = read_tool_result_artifact(outcome.artifact_path)
        assert restored == content
        assert hashlib.sha256(restored.encode("utf-8")).hexdigest() == outcome.artifact_sha256
        # 模型可见占位带引用 + sha256 + 预览 + 结构化后缀
        assert f"artifact_ref: {outcome.artifact_ref}" in budgeted
        assert f"sha256: {outcome.artifact_sha256}" in budgeted
        assert "--- 预览 ---" in budgeted
        assert "[工具结果预算] strategy=artifact" in budgeted
        assert f"artifact_ref={outcome.artifact_ref}" in budgeted

    def test_artifact_tail_preview_keeps_end(self, artifact_dir):
        _register("tail_artifact_tool", max_model_chars=1200, strategy=STRATEGY_ARTIFACT, preview=PREVIEW_TAIL)
        content = "HEAD-MARKER" + "m" * 6000 + "TAIL-MARKER"
        budgeted, _ = apply_tool_result_budget(content, tool_name="tail_artifact_tool", tool_call_id="call-t")
        assert "TAIL-MARKER" in budgeted
        assert "HEAD-MARKER" not in budgeted

    def test_artifact_write_failure_falls_back_to_truncate(self, artifact_dir, monkeypatch):
        _register("fallback_tool", max_model_chars=900, strategy=STRATEGY_ARTIFACT)

        def _boom(*args: Any, **kwargs: Any) -> dict[str, Any]:
            raise OSError("disk full")

        monkeypatch.setattr(
            "core.infrastructure.tool_result_budget.write_tool_result_artifact", _boom
        )
        content = "FALLBACK" + "f" * 5000
        budgeted, outcome = apply_tool_result_budget(content, tool_name="fallback_tool", tool_call_id="call-fb")
        # 成功调用不因落盘失败变失败：仍然返回预算化文本
        assert isinstance(budgeted, str)
        assert outcome is not None
        assert outcome.strategy == "artifact_fallback_truncate"
        assert "disk full" in outcome.fallback_reason
        assert len(budgeted) <= 900
        assert "[工具结果预算] strategy=artifact_fallback_truncate" in budgeted
        assert "fallback=OSError" in budgeted
        assert artifact_dir.exists() is False

    def test_budget_outcome_recorded_for_truncate_audit(self, artifact_dir):
        _register("audit_tool", max_model_chars=800, strategy=STRATEGY_TRUNCATE)
        _, outcome = apply_tool_result_budget("a" * 3000, tool_name="audit_tool", tool_call_id="call-audit")
        assert isinstance(outcome, ToolResultBudgetOutcome)
        assert outcome.fallback_reason == ""
        assert outcome.preview_direction == "head"


class TestEmptyOutputPlaceholder:
    def test_render_empty_content_gets_generic_placeholder(self):
        facts = package_tool_result_facts("", tool_name="empty_tool")
        rendered = render_tool_result_for_model(facts)
        assert EMPTY_TOOL_OUTPUT_PLACEHOLDER in rendered
        assert "[工具空输出]" in rendered

    def test_placeholder_text_is_new_marker_not_shell_marker(self):
        assert SHELL_EMPTY_MARKER not in EMPTY_TOOL_OUTPUT_PLACEHOLDER

    def test_shell_existing_marker_passes_through_unchanged(self):
        facts = package_tool_result_facts(SHELL_EMPTY_MARKER, tool_name="shell_tool")
        rendered = render_tool_result_for_model(facts)
        assert SHELL_EMPTY_MARKER in rendered
        assert EMPTY_TOOL_OUTPUT_PLACEHOLDER not in rendered

    def test_whitespace_only_content_gets_placeholder(self):
        facts = package_tool_result_facts("   \n  ", tool_name="ws_tool")
        rendered = render_tool_result_for_model(facts)
        assert "[工具空输出]" in rendered

    def test_handle_tool_result_binds_placeholder_for_empty_result(self):
        bridge = ToolLifecycleBridge(tool_executor_execute=lambda *a, **k: ("", None))
        messages: list = []
        bridge.handle_tool_result({"id": "call-empty", "name": "quiet_tool", "args": {}}, "", None, messages)
        assert isinstance(messages[0], ToolMessage)
        assert "[工具空输出]" in messages[0].content
        assert "truncated: false" in messages[0].content


class TestParallelBatchSafety:
    def test_concurrent_artifact_writes_isolated_by_call_id(self, artifact_dir):
        _register("parallel_tool", max_model_chars=600, strategy=STRATEGY_ARTIFACT)

        def _write(index: int) -> ToolResultBudgetOutcome:
            content = f"PARALLEL-{index}-" + "p" * 4000
            _, outcome = apply_tool_result_budget(
                content, tool_name="parallel_tool", tool_call_id=f"call-parallel-{index}"
            )
            assert outcome is not None and outcome.strategy == STRATEGY_ARTIFACT
            return outcome

        with ThreadPoolExecutor(max_workers=6) as pool:
            outcomes = list(pool.map(_write, range(12)))

        assert len({outcome.artifact_path for outcome in outcomes}) == 12
        for index, outcome in enumerate(outcomes):
            restored = read_tool_result_artifact(outcome.artifact_path)
            assert restored.startswith(f"PARALLEL-{index}-")
            assert compute_tool_result_digest(restored) == outcome.artifact_sha256

    def test_readonly_batch_binds_bounded_messages_in_order(self, artifact_dir, monkeypatch):
        _register("batch_read_tool", max_model_chars=700, strategy=STRATEGY_ARTIFACT)
        monkeypatch.setattr(
            ToolLifecycleBridge,
            "READONLY_TOOL_NAMES",
            {"batch_read_tool"},
        )

        def _executor(tool_name: str, tool_args: dict, *, tool_call_id: str = "") -> tuple:
            return (f"RESULT-{tool_call_id}-" + "b" * 5000, None)

        bridge = ToolLifecycleBridge(tool_executor_execute=_executor)
        calls = [
            {"id": f"call-batch-{i}", "name": "batch_read_tool", "args": {"i": i}}
            for i in range(4)
        ]
        messages: list = []
        action = bridge.execute_tools(calls, messages, max_parallel_readonly=4)

        assert action is None
        assert len(messages) == 4
        for index, message in enumerate(messages):
            assert isinstance(message, ToolMessage)
            assert message.tool_call_id == f"call-batch-{index}"
            assert len(_result_section(message.content)) <= 700
            assert "[工具结果预算] strategy=artifact" in message.content
            assert f"RESULT-call-batch-{index}" in message.content

    def test_readonly_batch_mixed_declared_and_undeclared(self, artifact_dir, monkeypatch):
        _register("batch_declared_tool", max_model_chars=500, strategy=STRATEGY_TRUNCATE)
        monkeypatch.setattr(
            ToolLifecycleBridge,
            "READONLY_TOOL_NAMES",
            {"batch_declared_tool", "batch_plain_tool"},
        )
        bridge = ToolLifecycleBridge(
            tool_executor_execute=lambda name, args, *, tool_call_id="": ("u" * 6000, None)
        )
        calls = [
            {"id": "call-plain", "name": "batch_plain_tool", "args": {}},
            {"id": "call-declared", "name": "batch_declared_tool", "args": {}},
        ]
        messages: list = []
        bridge.execute_tools(calls, messages, max_parallel_readonly=2)

        plain, declared = messages
        # 未声明工具与既有打包渲染路径逐字节等价（含渲染层默认限长截断）
        expected_plain = render_tool_result_for_model(
            package_tool_result_facts("u" * 6000, tool_name="batch_plain_tool")
        )
        assert plain.content == expected_plain
        assert "[工具结果预算]" not in plain.content
        assert len(_result_section(declared.content)) <= 500
        assert "strategy=truncate, original_chars=6000" in declared.content


class TestDescriptorOnlyExtraRoom:
    def test_declared_budget_below_default_shrinks_model_view(self):
        _register("small_tool", max_model_chars=800, strategy=STRATEGY_TRUNCATE)
        bridge = ToolLifecycleBridge(tool_executor_execute=lambda *a, **k: ("s" * 5000, None))
        messages: list = []
        bridge.handle_tool_result({"id": "call-small", "name": "small_tool", "args": {}}, "s" * 5000, None, messages)
        assert len(_result_section(messages[0].content)) <= 800
        assert "original_chars=5000" in messages[0].content

    def test_oversized_declared_budget_raises_inline_room(self):
        """声明高于默认限长的工具，未超预算内容整体直达模型。"""
        _register("roomy_tool", max_model_chars=9000, max_inline_chars=9000, strategy=STRATEGY_TRUNCATE)
        bridge = ToolLifecycleBridge(tool_executor_execute=lambda *a, **k: ("r" * 6000, None))
        messages: list = []
        bridge.handle_tool_result({"id": "call-roomy", "name": "roomy_tool", "args": {}}, "r" * 6000, None, messages)
        assert messages[0].content.count("r") >= 6000
        assert "[工具结果预算]" not in messages[0].content
