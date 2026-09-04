#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工具结果处理测试 (test_tool_result.py)

测试 core/infrastructure/tool_result.py 中的：
- truncate_result: 超长结果截断
- format_tool_message: 工具消息格式化
- DEFAULT_MAX_CHARS 常量
"""

import sys
import json
from pathlib import Path

import pytest
from core.infrastructure.tool_result import (
    extract_tool_result_semantics,
    truncate_result,
    package_tool_result,
    package_tool_result_facts,
    project_runtime_tool_metadata,
    tool_result_facts_payload,
    render_tool_result_for_model,
    format_tool_message,
    infer_tool_business_success,
    infer_tool_execution_success,
    DEFAULT_MAX_CHARS,
)


class TestTruncateResult:
    """truncate_result 测试"""

    def test_short_result_not_truncated(self):
        """短结果不截断"""
        result, truncated = truncate_result("hello", max_chars=100)
        assert result == "hello"
        assert truncated is False

    def test_result_at_limit_not_truncated(self):
        """等于限制长度不截断"""
        s = "A" * 10
        result, truncated = truncate_result(s, max_chars=10)
        assert result == s
        assert truncated is False

    def test_result_over_limit_truncated(self):
        """超过限制被截断"""
        s = "A" * 100
        result, truncated = truncate_result(s, max_chars=50)
        assert len(result) < len(s)
        assert truncated is True
        assert "[...结果已截断" in result

    def test_truncation_preserves_prefix(self):
        """截断保留前缀"""
        result, _ = truncate_result("ABCDEFGHIJ", max_chars=5)
        assert result.startswith("ABCDE")

    def test_default_max_chars(self):
        """使用默认限制值"""
        assert DEFAULT_MAX_CHARS == 4000

    def test_non_string_result_converted(self):
        """非字符串结果被转为字符串"""
        result, _ = truncate_result(12345)
        assert isinstance(result, str)
        assert "12345" in result

    def test_empty_string(self):
        """空字符串"""
        result, truncated = truncate_result("")
        assert result == ""
        assert truncated is False

    def test_max_chars_zero(self):
        """max_chars=0 时截断所有内容"""
        result, truncated = truncate_result("hello", max_chars=0)
        assert truncated is True
        assert "[...结果已截断" in result

    def test_list_result_converted(self):
        """列表结果被转为字符串"""
        result, _ = truncate_result([1, 2, 3], max_chars=100)
        assert isinstance(result, str)
        assert "1" in result

    def test_package_tool_result_keeps_navigation_only_in_runtime_metadata(self):
        raw = (
            "[文件] demo.py\n"
            "[编码] utf-8 | [行数] 400 (已截断) | [大小] 10.0 KB\n"
            "[区间] 第 1-120 行 | 已显示 120 行 | 剩余 280 行\n"
            "[阅读导航] 下一步按目标选择；只有目标确实需要相邻下文时，才读取 offset=120, max_lines=120。\n\n"
            "--- Content ---\n"
            + ("A" * 5000)
        )

        packaged = package_tool_result(raw, tool_name="read_file_tool", max_chars=240)

        assert packaged.truncated is True
        assert packaged.result_kind == "file_read"
        assert "offset=120" in packaged.continuation_hint
        assert "阅读导航=" not in packaged.content
        assert "[截断信息]" in packaged.content or "[...结果已截断" in packaged.content

    def test_package_tool_result_compacts_file_read_with_preview(self):
        raw = (
            "[文件] demo.py\n"
            "[编码] utf-8 | [行数] 400 (已截断) | [大小] 10.0 KB\n"
            "[区间] 第 1-120 行 | 已显示 120 行 | 剩余 280 行\n"
            "[阅读导航] 下一步按目标选择；只有目标确实需要相邻下文时，才读取 offset=120, max_lines=80。\n\n"
            "--- Content ---\n"
            + "\n".join(f"第 {i} 行" for i in range(1, 160))
        )

        packaged = package_tool_result(raw, tool_name="read_file_tool", max_chars=360)

        assert packaged.truncated is True
        assert packaged.strategy in {"structured_compact", "annotated_truncate", "legacy_prefix_truncate"}
        assert "Content Preview" in packaged.content or "[截断信息]" in packaged.content

    def test_package_tool_result_compacts_search_result(self):
        raw = (
            "[搜索] 正则: Demo\n"
            "[搜索] 目录: core\n"
            "[搜索] 类型: .py\n"
            "[搜索] 找到 9 个匹配，分布在 4 个文件\n"
            "[搜索摘要]\n"
            "- core/a.py | 命中 3 处 | 行 1, 4, 8\n\n"
            + "\n".join(
                [f"📁 core/{name}.py\n" + "\n".join([f"  → 第 {i} 行 | demo" for i in range(1, 7)]) for name in ("a", "b", "c", "d")]
            )
        )

        packaged = package_tool_result(raw, tool_name="grep_search_tool", max_chars=320)

        assert packaged.truncated is True
        assert packaged.result_kind == "search"
        assert packaged.strategy in {"structured_compact", "annotated_truncate", "legacy_prefix_truncate"}

    def test_package_tool_result_structurally_compacts_code_context_graph(self):
        payload = {
            "status": "ok",
            "mode": "explore",
            "query": "conversation chain",
            "summary": {"resultCount": 20, "totalResultCount": 80, "hasMore": True},
            "resultLimit": {"requested": 50, "applied": 8, "capped": True},
            "results": [
                {
                    "kind": "symbol",
                    "name": f"symbol_{index}",
                    "qualifiedName": f"module.symbol_{index}",
                    "path": f"core/module_{index}.py",
                    "line": index + 1,
                    "preview": "P" * 600,
                }
                for index in range(20)
            ],
            "contexts": [
                {
                    "path": f"core/module_{index}.py",
                    "language": "python",
                    "summary": "S" * 400,
                    "snippet": "X" * 1200,
                    "symbols": [{"name": f"symbol_{index}", "kind": "function", "line": 1}],
                }
                for index in range(8)
            ],
        }

        packaged = package_tool_result(
            json.dumps(payload, ensure_ascii=False),
            tool_name="code_symbol_tool",
            max_chars=900,
        )

        assert packaged.truncated is True
        assert packaged.result_kind == "code_context_graph"
        assert packaged.strategy == "structured_compact"
        compact = json.loads(packaged.content)
        assert compact["resultLimit"]["applied"] == 8
        assert compact["truncationGuard"]["strategy"] == "structured_compact"
        assert len(compact["results"]) <= 8
        assert len(packaged.content) <= 1600

    def test_package_tool_result_compacts_source_collection_context_with_paging_ids(self):
        payload = {
            "status": "ok",
            "contextKind": "source_collection_stage_task_context",
            "contextMode": "full",
            "counts": {
                "recordCount": 15,
                "excludedSourceCount": 2,
                "returnedRecordCount": 10,
                "candidateCount": 15,
                "returnedCandidateCount": 5,
            },
            "excludedSourceSummary": {
                "excludedCount": 2,
                "activeRecordCount": 15,
                "rawRecordCount": 17,
                "excluded": [{"recordId": "record-excluded-1", "reason": "no_effective_content"}],
            },
            "candidatePage": {
                "offset": 0,
                "limit": 5,
                "returned": 5,
                "total": 15,
                "hasMore": True,
                "nextOffset": 5,
            },
            "candidates": [
                {
                    "candidateId": f"candidate-{index}",
                    "title": "Long candidate title " + ("X" * 240),
                    "sourceKind": "论文网页/DOI",
                    "qualityBucket": "pending",
                    "summary": "This is only a preview and must not be used as final evidence.",
                    "abstract": "A" * 1200,
                }
                for index in range(5)
            ],
            "records": [{"recordId": f"record-{index}", "title": "R" * 1000} for index in range(10)],
            "usage": {
                "readTool": "source_collection_context_tool",
                "writebackTool": "source_collection_stage_writeback_tool",
            },
        }

        packaged = package_tool_result(
            json.dumps(payload, ensure_ascii=False),
            tool_name="source_collection_context_tool",
            max_chars=900,
        )

        assert packaged.truncated is True
        assert packaged.result_kind == "source_collection_context"
        assert packaged.strategy == "structured_compact"
        assert "candidate-0" in packaged.content
        assert "candidate-4" in packaged.content
        assert "candidate_offset=5" in packaged.content
        assert "hasMore" in packaged.content
        assert packaged.continuation_hint
        compact = json.loads(packaged.content)
        assert compact["fieldMode"] == "preview_only"
        assert compact["candidateFieldsTruncated"] is True
        assert compact["doNotUsePreviewAsEvidence"] is True
        assert compact["visibleCandidateCount"] == 5
        assert compact["omittedReturnedCandidateCount"] == 0
        assert compact["excludedSourceSummary"]["excludedCount"] == 2
        assert "summaryPreview" in compact["candidates"][0]
        assert "summary" not in compact["candidates"][0]

    def test_package_tool_result_source_collection_context_strips_non_page_payload(self):
        payload = {
            "status": "ok",
            "contextKind": "source_collection_stage_task_context",
            "contextMode": "minimal",
            "counts": {
                "recordCount": 34,
                "excludedSourceCount": 50,
                "returnedRecordCount": 5,
                "candidateCount": 34,
                "returnedCandidateCount": 5,
            },
            "excludedSourceSummary": {
                "excludedCount": 50,
                "activeRecordCount": 34,
                "rawRecordCount": 84,
                "excluded": [
                    {
                        "recordId": f"excluded-{index}",
                        "title": "Noise source " + ("X" * 200),
                        "reason": "no_effective_content",
                    }
                    for index in range(50)
                ],
            },
            "candidatePage": {
                "offset": 5,
                "limit": 5,
                "returned": 5,
                "total": 34,
                "hasMore": True,
                "nextOffset": 10,
            },
            "candidates": [
                {
                    "candidateId": f"candidate-{index}",
                    "title": "Predictive coding source " + ("Y" * 180),
                    "sourceKind": "paper",
                    "qualityBucket": "pending",
                    "summary": "Only a short preview should remain. " * 30,
                    "contentExtraction": {
                        "status": "stale",
                        "summary": "A stale previous extraction must not be shown as current evidence. " * 40,
                    },
                    "latestAssessment": {"decision": "needs_more_info", "notes": "N" * 800},
                }
                for index in range(5, 10)
            ],
            "usage": {
                "readTool": "source_collection_context_tool",
                "writebackTool": "source_collection_stage_writeback_tool",
            },
        }

        packaged = package_tool_result(
            json.dumps(payload, ensure_ascii=False),
            tool_name="source_collection_context_tool",
            max_chars=900,
        )

        assert packaged.truncated is True
        compact = json.loads(packaged.content)
        assert len(packaged.content) <= 1600
        assert compact["contextMode"] == "minimal_from_tool_result"
        assert compact["excludedSourceSummary"] == {
            "excludedCount": 50,
            "activeRecordCount": 34,
            "rawRecordCount": 84,
        }
        assert compact["candidateIds"] == [f"candidate-{index}" for index in range(5, 10)]
        assert "candidate_offset=10" in compact["usage"]["continuationHint"]
        assert "contentExtraction" not in compact["candidates"][0]
        assert "latestAssessment" not in compact["candidates"][0]
        assert "excluded-49" not in packaged.content

    def test_package_tool_result_preserves_governed_evidence_context_when_long(self):
        payload = {
            "status": "ok",
            "contextKind": "source_collection_stage_task_context",
            "contextMode": "retry_evidence",
            "counts": {"candidateCount": 10, "returnedCandidateCount": 5},
            "candidatePage": {
                "offset": 0,
                "limit": 5,
                "returned": 5,
                "total": 10,
                "hasMore": True,
                "nextOffset": 5,
            },
            "candidates": [
                {
                    "candidateId": f"candidate-evidence-{index}",
                    "title": f"Predictive coding evidence candidate {index}",
                    "sourceKind": "paper",
                    "doi": f"10.0000/evidence-{index}",
                    "summary": "Governed source-collection abstract metadata. " * 40,
                    "evidenceRefs": [
                        {"type": "doi", "id": f"10.0000/evidence-{index}", "label": f"Evidence {index}"}
                    ],
                    "evidenceScope": "collected_summary_metadata",
                }
                for index in range(5)
            ],
            "usage": {
                "readTool": "source_collection_context_tool",
                "writebackTool": "source_collection_stage_writeback_tool",
                "retryInstruction": "只补这些候选的证据锚点。",
                "evidenceInstruction": "摘要不等于全文，不得虚构页码、引语或全文结论。",
            },
        }

        packaged = package_tool_result(
            json.dumps(payload, ensure_ascii=False),
            tool_name="source_collection_context_tool",
            max_chars=4000,
        )

        assert packaged.truncated is True
        assert packaged.strategy == "structured_compact"
        compact = json.loads(packaged.content)
        assert compact["contextMode"] == "retry_evidence_from_tool_result"
        assert compact["fieldMode"] == "evidence_source"
        assert compact["doNotUsePreviewAsEvidence"] is False
        assert compact["candidateIds"] == [f"candidate-evidence-{index}" for index in range(5)]
        assert "summary" in compact["candidates"][0]
        assert "summaryPreview" not in compact["candidates"][0]
        assert compact["candidates"][0]["evidenceRefs"][0]["id"] == "10.0000/evidence-0"
        assert compact["usage"]["evidenceInstruction"].startswith("摘要不等于全文")
        assert "context_mode=retry_evidence" in compact["usage"]["continuationHint"]
        assert "context_mode=retry_evidence" in packaged.continuation_hint

    def test_package_tool_result_keeps_evidence_anchors_when_evidence_context_exceeds_budget(self):
        payload = {
            "status": "ok",
            "contextKind": "source_collection_stage_task_context",
            "contextMode": "evidence",
            "counts": {"candidateCount": 5, "returnedCandidateCount": 5},
            "candidatePage": {
                "offset": 0,
                "limit": 5,
                "returned": 5,
                "total": 5,
                "hasMore": False,
                "nextOffset": None,
            },
            "candidates": [
                {
                    "candidateId": f"candidate-evidence-budget-{index}",
                    "title": f"Predictive coding evidence candidate {index}",
                    "sourceKind": "paper",
                    "doi": f"10.0000/evidence-budget-{index}",
                    "summary": "Governed source-collection abstract metadata. " * 80,
                    "evidenceRefs": [
                        {"type": "doi", "id": f"10.0000/evidence-budget-{index}", "label": f"Evidence {index}"}
                    ],
                    "evidenceScope": "collected_summary_metadata",
                }
                for index in range(5)
            ],
            "usage": {
                "readTool": "source_collection_context_tool",
                "writebackTool": "source_collection_stage_writeback_tool",
                "evidenceInstruction": "摘要不等于全文，不得虚构页码、引语或全文结论。",
            },
        }

        packaged = package_tool_result(
            json.dumps(payload, ensure_ascii=False),
            tool_name="source_collection_context_tool",
            max_chars=1600,
        )

        compact = json.loads(packaged.content)
        assert compact["fieldMode"] == "evidence_source"
        assert compact["doNotUsePreviewAsEvidence"] is False
        assert compact["candidates"]
        assert all(item.get("evidenceRefs") for item in compact["candidates"])
        assert all("summaryPreview" not in item for item in compact["candidates"])

    def test_package_tool_result_preserves_ingestion_steward_packet_when_long(self):
        approved_ids = ["candidate-approved-1", "candidate-approved-2"]
        payload = {
            "status": "ok",
            "contextKind": "source_collection_stage_task_context",
            "contextMode": "compact",
            "stageId": "ingestion",
            "counts": {"candidateCount": 39, "returnedCandidateCount": 2},
            "candidatePage": {"offset": 0, "limit": 80, "returned": 2, "total": 2, "hasMore": False},
            "candidates": [
                {
                    "candidateId": candidate_id,
                    "title": f"Approved evidence {index}",
                    "sourceKind": "paper",
                    "sourceRecordId": f"record-approved-{index}",
                    "summary": "Governed source-collection abstract metadata. " * 80,
                }
                for index, candidate_id in enumerate(approved_ids, start=1)
            ],
            "stewardActionPacket": {
                "schemaVersion": 1,
                "packetKind": "knowledge_steward_approved_candidate_action",
                "action": "writeback_approved_candidates",
                "recommendedStatus": "completed",
                "approvedCandidateIds": approved_ids,
                "approvedCandidateCount": 2,
                "deferredCandidateCounts": {"pending": 0, "rejected": 5, "needs_revision": 32},
                "writebackTool": "source_collection_stage_writeback_tool",
                "writebackResultSkeleton": {
                    "approvedCandidateIds": approved_ids,
                    "candidate_summary": {
                        "approved": {"count": 2, "candidateIds": approved_ids, "candidates": [{"noise": "x" * 4000}]},
                        "deferredCounts": {"pending": 0, "rejected": 5, "needs_revision": 32},
                    },
                    "steward_assessment": {"decision": "approved", "reason": "quality gate passed"},
                },
                "instructions": ["Use approvedCandidateIds and write back immediately."],
            },
            "usage": {
                "readTool": "source_collection_context_tool",
                "writebackTool": "source_collection_stage_writeback_tool",
            },
        }

        packaged = package_tool_result(
            json.dumps(payload, ensure_ascii=False),
            tool_name="source_collection_context_tool",
            max_chars=2400,
        )

        assert packaged.truncated is True
        assert packaged.strategy == "structured_compact"
        compact = json.loads(packaged.content)
        assert compact["fieldMode"] == "evidence_source"
        assert compact["doNotUsePreviewAsEvidence"] is False
        assert compact["stewardActionPacket"]["approvedCandidateIds"] == approved_ids
        assert compact["stewardActionPacket"]["writebackResultSkeleton"]["approvedCandidateIds"] == approved_ids
        assert "candidates" not in compact["stewardActionPacket"]["writebackResultSkeleton"]["candidate_summary"]["approved"]
        assert compact["candidates"][0]["evidenceRefs"][0]["id"] == "record-approved-1"
        assert "summaryPreview" not in compact["candidates"][0]

    def test_compact_ingestion_context_does_not_duplicate_candidate_bodies_in_steward_packet(self):
        from core.web.services.team_workflow.source_collection_context import (
            compact_source_collection_stage_task_context,
        )

        approved_ids = [f"candidate-{index}" for index in range(40)]
        large_candidates = [
            {
                "candidateId": candidate_id,
                "title": "Approved evidence",
                "summary": "large evidence body " * 200,
            }
            for candidate_id in approved_ids
        ]
        context = {
            "contextMode": "compact",
            "stageId": "ingestion",
            "candidates": large_candidates[:5],
            "candidatePage": {"returned": 5, "total": 40, "hasMore": False},
            "stewardActionPacket": {
                "schemaVersion": 1,
                "approvedCandidateIds": approved_ids,
                "approvedCandidateCount": 40,
                "writebackTool": "source_collection_stage_writeback_tool",
                "writebackResultSkeleton": {
                    "approvedCandidateIds": approved_ids,
                    "candidate_summary": {
                        "approved": {
                            "count": 40,
                            "candidateIds": approved_ids,
                            "candidates": large_candidates,
                        }
                    },
                },
            },
        }

        compact = compact_source_collection_stage_task_context(context)
        packet = compact["stewardActionPacket"]

        assert packet["approvedCandidateIds"] == approved_ids
        assert packet["writebackResultSkeleton"]["approvedCandidateIds"] == approved_ids
        assert "candidates" not in packet["writebackResultSkeleton"]["candidate_summary"]["approved"]
        assert len(json.dumps(compact, ensure_ascii=False)) < 16_000

    def test_package_tool_result_compacts_source_collection_context_with_record_paging_ids(self):
        payload = {
            "status": "ok",
            "contextKind": "source_collection_stage_task_context",
            "contextMode": "full",
            "counts": {
                "recordCount": 15,
                "returnedRecordCount": 5,
                "candidateCount": 0,
                "returnedCandidateCount": 0,
            },
            "recordPage": {
                "offset": 0,
                "limit": 5,
                "returned": 5,
                "total": 15,
                "hasMore": True,
                "nextOffset": 5,
            },
            "candidatePage": {
                "offset": 0,
                "limit": 5,
                "returned": 0,
                "total": 0,
                "hasMore": False,
                "nextOffset": None,
            },
            "records": [
                {
                    "recordId": f"dprec-2026062812000000000{i}-record{i}",
                    "title": "Long raw record title " + ("X" * 240),
                    "summary": "The raw record text is long and must be compacted.",
                    "sourceType": "paper",
                    "doi": f"10.0000/raw-record-{i}",
                }
                for i in range(5)
            ],
            "candidates": [],
            "usage": {
                "readTool": "source_collection_context_tool",
                "writebackTool": "source_collection_stage_writeback_tool",
            },
        }

        packaged = package_tool_result(
            json.dumps(payload, ensure_ascii=False),
            tool_name="source_collection_context_tool",
            max_chars=900,
        )

        assert packaged.truncated is True
        assert packaged.result_kind == "source_collection_context"
        assert packaged.strategy == "structured_compact"
        assert "dprec-20260628120000000000-record0" in packaged.content
        assert "record_offset=5" in packaged.content
        compact = json.loads(packaged.content)
        assert compact["recordPage"]["hasMore"] is True
        assert compact["recordIds"][0] == "dprec-20260628120000000000-record0"
        assert compact["usage"]["recordContinuationHint"]


class TestFormatToolMessage:
    """format_tool_message 测试"""

    def test_returns_string_and_call_id(self):
        """返回 (result_str, tool_call_id) 元组"""
        result_str, call_id = format_tool_message(
            {"id": "call_123"}, "result text", None
        )
        assert isinstance(result_str, str)
        assert isinstance(call_id, str)
        assert "result text" in result_str

    def test_none_id_handled(self):
        """None ID 被安全处理"""
        result_str, call_id = format_tool_message(
            {"id": None}, "result"
        )
        assert call_id == ""

    def test_missing_id_handled(self):
        """缺少 id 被安全处理"""
        result_str, call_id = format_tool_message({}, "result")
        assert call_id == ""

    def test_long_result_truncated_in_format(self):
        """长结果在格式化时被截断"""
        long_result = "X" * 5000
        result_str, _ = format_tool_message(
            {"id": "call_1"}, long_result
        )
        assert len(result_str) <= DEFAULT_MAX_CHARS
        assert "[Tool Result Facts]" in result_str
        assert "truncated: true" in result_str
        assert "[...结果已截断" in result_str

    def test_action_param_accepted(self):
        """action 参数被接受（当前未使用）"""
        result_str, call_id = format_tool_message(
            {"id": "call_1"}, "result", action="restart"
        )
        assert result_str is not None
        assert call_id is not None

    def test_model_render_includes_facts_without_summarizing_failure(self):
        facts = package_tool_result_facts(
            {"status": "success", "exitCode": 255, "message": "process failed"},
            tool_name="demo_tool",
        )

        rendered = render_tool_result_for_model(facts)

        assert "toolName: demo_tool" in rendered
        assert "semanticStatus: failed" in rendered
        assert "exitCode: 255" in rendered
        assert "failureClass: process_exit" in rendered
        assert "summary:" not in rendered.lower()

    def test_model_render_strips_tool_continuation_and_workflow_directives(self):
        payload = {
            "status": "ok",
            "records": [{"recordId": "paper-1", "title": "Fact record"}],
            "usage": {
                "continuationHint": "继续调用 source_collection_context_tool(candidate_offset=5)",
                "retryInstruction": "请改用 retry_missing 模式重试",
                "evidenceInstruction": "下一步必须补齐证据",
            },
            "nextAction": "调用 writeback_tool",
            "suggested_action": "安装依赖后重试",
        }

        facts = package_tool_result_facts(
            payload,
            tool_name="source_collection_context_tool",
        )
        rendered = render_tool_result_for_model(facts)

        assert "paper-1" in rendered
        assert "continuationHint" not in rendered
        assert "retryInstruction" not in rendered
        assert "evidenceInstruction" not in rendered
        assert "nextAction" not in rendered
        assert "suggested_action" not in rendered
        assert "继续调用" not in rendered
        assert "retry_missing" not in rendered
        assert "安装依赖后重试" not in rendered
        assert "continuationHint" not in tool_result_facts_payload(facts)

    def test_model_render_strips_inline_recovery_and_structured_action_routes(self):
        payload = {
            "status": "error",
            "message": "参数校验失败。请按工具描述修正参数名和类型后重试。",
            "nextActions": ["调用 source_collection_context_tool"],
            "replacement": {"mode": "inspect", "file_path": "core/demo.py"},
            "recovery": "请使用 inspect 模式重新查询。",
        }

        rendered = render_tool_result_for_model(
            package_tool_result_facts(payload, tool_name="probe_tool")
        )

        assert "参数校验失败" in rendered
        assert "请按工具描述" not in rendered
        assert "nextActions" not in rendered
        assert "source_collection_context_tool" not in rendered
        assert "replacement" not in rendered
        assert "core/demo.py" not in rendered
        assert "recovery" not in rendered
        assert "请使用 inspect" not in rendered

    def test_model_render_keeps_file_read_range_but_not_reading_navigation(self):
        raw = (
            "[文件] demo.py\n"
            "[区间] 第 1-20 行 | 已显示 20 行 | 剩余 80 行\n"
            "[阅读导航] 继续调用 read_file_tool(offset=20, max_lines=20)。\n\n"
            "--- Content ---\n"
            "def factual_result():\n    return 1\n"
        )

        rendered = render_tool_result_for_model(
            package_tool_result_facts(raw, tool_name="read_file_tool")
        )

        assert "第 1-20 行" in rendered
        assert "阅读导航" not in rendered
        assert "继续调用 read_file_tool" not in rendered

    def test_runtime_metadata_keeps_navigation_outside_model_projection(self):
        raw = (
            "[文件] demo.py\n"
            "[区间] 第 1-20 行 | 已显示 20 行 | 剩余 80 行\n"
            "[阅读导航] 继续调用 read_file_tool(offset=20, max_lines=20)。\n\n"
            "--- Content ---\n"
            "def factual_result():\n    return 1\n"
        )

        runtime = project_runtime_tool_metadata(raw, tool_name="read_file_tool")
        rendered = render_tool_result_for_model(
            package_tool_result_facts(raw, tool_name="read_file_tool")
        )

        assert "offset=20" in runtime.continuation_hint
        assert "offset=20" not in rendered


class TestInferToolBusinessSuccess:
    """业务层工具结果成功性推断。"""

    @pytest.mark.parametrize(
        "result",
        [
            {"status": "blocked", "message": "policy blocked"},
            {"status": "policy_blocked", "message": "policy blocked"},
            {"status": "failed", "message": "send failed"},
            {"status": "cancelled", "message": "interrupted"},
            {"status": "fail", "message": "legacy failure token"},
            {"status": "failure", "message": "legacy failure token"},
            {"status": "error", "message": "runtime error"},
            {"status": "no_result", "message": "empty payload"},
            {"status": "submitted", "message": "async accepted"},
            {"status": "in_progress", "message": "still running"},
            {"status": "timed_out", "message": "request timed out"},
            {"status": "timeout", "message": "tool call timed out"},
        ],
    )
    def test_non_success_status_is_business_failure_dict(self, result):
        assert infer_tool_business_success(result) is False

    @pytest.mark.parametrize(
        "result",
        [
            '{"status":"blocked","error":"policy limited"}',
            '{"status":"policy_blocked","error":"policy limited"}',
            '{"error":"RuntimeError","status":"failed"}',
            '{"status":"cancelled","error":"User stop requested"}',
            '{"status":"no_result"}',
            '{"status":"submitted"}',
            '{"status":"in_progress"}',
            '{"status":"timed_out"}',
            '{"status":"timeout"}',
        ],
    )
    def test_non_success_status_is_business_failure_json(self, result):
        assert infer_tool_business_success(result) is False

    @pytest.mark.parametrize(
        "result",
        [
            "blocked",
            "policy_blocked",
        ],
    )
    def test_plain_status_text_is_business_failure(self, result):
        assert infer_tool_business_success(result) is False

    def test_timeout_plain_text_is_business_failure(self):
        assert infer_tool_business_success("timeout") is False

    def test_prefixed_plain_text_is_business_failure(self):
        assert infer_tool_business_success(" [错误] something failed") is False

    def test_binary_plain_text_is_business_failure_prefix(self):
        assert infer_tool_business_success("[错误] binary failure".encode("utf-8")) is False

    def test_bytearray_plain_text_is_business_failure_prefix(self):
        assert infer_tool_business_success(bytearray("[错误] bytearray failure".encode("utf-8"))) is False

    def test_truncate_result_decodes_binary_payload(self):
        result, truncated = truncate_result("[错误] binary payload".encode("utf-8"))

        assert truncated is False
        assert result == "[错误] binary payload"

    def test_ok_false_json_string_is_business_failure(self):
        result = '{"error":"RuntimeError","message":"cannot schedule new futures after shutdown","ok":false,"status":"failed"}'
        assert infer_tool_business_success(result) is False

    def test_failed_dict_is_business_failure(self):
        assert infer_tool_business_success({"status": "failed", "message": "send failed"}) is False

    def test_nonzero_exit_code_dict_is_business_failure_even_with_success_status(self):
        payload = {"status": "success", "exitCode": 255, "message": "process failed"}

        assert infer_tool_business_success(payload) is False
        semantics = extract_tool_result_semantics(payload)
        envelope = package_tool_result(payload)

        assert semantics["semanticStatus"] == "failed"
        assert semantics["exitCode"] == 255
        assert semantics["failureClass"] == "process_exit"
        assert envelope.semantic_status == "failed"
        assert envelope.exit_code == 255

    def test_plain_text_is_success(self):
        assert infer_tool_business_success("normal output") is True

    def test_multiline_jsonl_is_not_misreported_as_parse_failure(self, monkeypatch):
        import core.infrastructure.tool_result as tr

        warnings = []
        monkeypatch.setattr(tr._debug_logger, "warning", lambda *a, **k: warnings.append((a, k)))

        result = '{"type":"session_start","ts":1}\n{"type":"debug","ts":2}'
        assert infer_tool_business_success(result) is True
        assert warnings == []

        assert infer_tool_business_success('{"status":"failed"}') is False

    def test_completed_terminal_nonzero_exit_keeps_transport_completion_semantics(self):
        payload = {
            "status": "completed",
            "terminalSessionId": "sandbox-nonzero",
            "sessionOpen": False,
            "exitCode": 1,
            "outcomeStatus": "nonzero_exit",
            "formattedOutput": "[WARNING | Exit Code: 1]\ncommand failed",
        }

        assert infer_tool_business_success(payload) is False
        assert infer_tool_execution_success(payload) is True
        semantics = extract_tool_result_semantics(payload)
        envelope = package_tool_result(payload)

        assert semantics["semanticStatus"] == "completed"
        assert semantics["exitCode"] == 1
        assert semantics["failureClass"] == "process_exit"
        assert envelope.semantic_status == "completed"
        assert envelope.exit_code == 1

    def test_error_prefix_is_failure(self):
        assert infer_tool_business_success("[错误] something failed") is False

    def test_tool_argument_error_prefix_is_failure(self):
        payload = "[工具参数错误] grep_search_tool 参数不符合当前工具签名。"

        assert infer_tool_business_success(payload) is False
        semantics = extract_tool_result_semantics(payload)
        envelope = package_tool_result(payload)

        assert semantics["semanticStatus"] == "failed"
        assert semantics["failureClass"] == "tool_argument_error"
        assert envelope.semantic_status == "failed"
        assert envelope.failure_class == "tool_argument_error"

    def test_low_quality_search_prefix_is_degraded_semantics(self):
        payload = "[搜索质量不足] 公开搜索未返回可采信的结果。"

        semantics = extract_tool_result_semantics(payload)
        envelope = package_tool_result(payload)

        assert semantics["semanticStatus"] == "degraded"
        assert semantics["failureClass"] == "low_quality_search_results"
        assert envelope.semantic_status == "degraded"
        assert envelope.failure_class == "low_quality_search_results"

    def test_bom_prefixed_dict_status_is_business_failure(self):
        assert infer_tool_business_success({"status": "\ufefffailed", "error": "policy limited"}) is False
        assert infer_tool_business_success({"status": "\ufeffsuccess", "message": "ok"}) is True

    def test_bom_prefixed_string_status_is_business_failure(self):
        assert infer_tool_business_success("\ufeffblocked") is False
        assert infer_tool_business_success("\ufeffpolicy_blocked") is False

    def test_bom_prefixed_json_bytes_is_business_failure(self):
        payload = b"\xef\xbb\xbf{\"status\":\"failed\",\"error\":\"policy limited\"}"
        assert infer_tool_business_success(payload) is False

    def test_exec_failure_text_is_business_failure_with_exit_code(self):
        payload = "[EXEC FAILURE | Exit Code: 1]\npytest failed"

        assert infer_tool_business_success(payload) is False
        semantics = extract_tool_result_semantics(payload)
        envelope = package_tool_result(payload)

        assert semantics["semanticStatus"] == "failed"
        assert semantics["exitCode"] == 1
        assert semantics["failureClass"] == "process_exit"
        assert envelope.semantic_status == "failed"
        assert envelope.exit_code == 1

    def test_warning_exit_code_text_is_business_failure_with_exit_code(self):
        payload = "[WARNING | Exit Code: 255]\n[STDERR]\nThe system cannot find the path specified."

        assert infer_tool_business_success(payload) is False
        semantics = extract_tool_result_semantics(payload)
        envelope = package_tool_result(payload)

        assert semantics["semanticStatus"] == "failed"
        assert semantics["exitCode"] == 255
        assert semantics["failureClass"] == "process_exit"
        assert envelope.semantic_status == "failed"
        assert envelope.exit_code == 255
        assert envelope.failure_class == "process_exit"

    def test_cross_platform_warning_is_not_business_success(self):
        payload = "[跨平台警告] 在 Windows 上检测到 Unix shell 片段: pytest -q | head -5"

        assert infer_tool_business_success(payload) is False
        semantics = extract_tool_result_semantics(payload)
        envelope = package_tool_result(payload)

        assert semantics["semanticStatus"] == "degraded"
        assert semantics["failureClass"] == "cross_platform_command"
        assert envelope.semantic_status == "degraded"
        assert envelope.failure_class == "cross_platform_command"

    def test_security_block_is_not_business_success(self):
        payload = "[安全拦截] [Whitelist Block] 命令包含危险字符：|"

        assert infer_tool_business_success(payload) is False
        semantics = extract_tool_result_semantics(payload)

        assert semantics["semanticStatus"] == "blocked"
        assert semantics["failureClass"] == "security_block"

    def test_missing_mapped_test_is_not_business_success(self):
        payload = "[运行测试] 未找到对应测试文件\n提示: 请先创建测试文件，或手动运行 pytest"

        assert infer_tool_business_success(payload) is False
        semantics = extract_tool_result_semantics(payload)

        assert semantics["semanticStatus"] == "failed"
        assert semantics["failureClass"] == "missing_mapped_test"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
