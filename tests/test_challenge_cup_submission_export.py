from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import challenge_cup_submission_export as exporter


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "https://doi.org/10.1016/S1473-3099(20)30149-3",
            "https://doi.org/10.1016/S1473-3099(20)30149-3",
        ),
        (
            "https://doi.org/10.1016/j.cell.2022.04.024（已核验）",
            "https://doi.org/10.1016/j.cell.2022.04.024",
        ),
        (
            "doi: 10.1002/(SICI)1097-0134(19990701)37:1<1::AID-PROT1>3.0.CO;2-Z",
            "https://doi.org/10.1002/(SICI)1097-0134(19990701)37:1<1::AID-PROT1>3.0.CO;2-Z",
        ),
        ("PMID: 12345678", "https://pubmed.ncbi.nlm.nih.gov/12345678/"),
        ("PMC5650490 全文", "https://pmc.ncbi.nlm.nih.gov/articles/PMC5650490/"),
        ("MNRAS; arXiv:2002.06892", "https://arxiv.org/abs/2002.06892"),
        ("arXiv:gr-qc/9403008", "https://arxiv.org/abs/gr-qc/9403008"),
        ("NCBI Bookshelf NBK207181", "https://www.ncbi.nlm.nih.gov/books/NBK207181/"),
    ],
)
def test_normalize_source_url_preserves_doi_parentheses_and_strips_annotations(
    raw: str, expected: str | None
) -> None:
    assert exporter.normalize_source_url(raw) == expected


@pytest.mark.parametrize(
    ("total_values", "review", "expected"),
    [
        (
            ["31", "26", "30"],
            "总分核对：A=5+4+5+4+5+4+4=31；B=26；C=30。",
            {"A": "31", "B": "26", "C": "30"},
        ),
        (
            ["26", "33", "25"],
            "候选 A=7+4+3+3+3+3+3=26；候选 C=1+4+4+4+4+4+4=25。",
            {"A": "26", "B": "33", "C": "25"},
        ),
        (
            ["26", "29", "27"],
            "复核：C=2+5+4+4+4+4+4=27。",
            {"A": "26", "B": "29", "C": "27"},
        ),
    ],
)
def test_parse_scores_does_not_treat_dimension_formula_as_total(
    total_values: list[str], review: str, expected: dict[str, str]
) -> None:
    header = ["维度", "候选 A", "候选 B", "候选 C", "说明"]
    total = ["总分", *total_values, ""]

    assert exporter.parse_scores(header, total, review) == expected


@pytest.mark.parametrize(
    ("source_type", "contribution", "expected"),
    [
        ("同行评议 + 反证", "直接反驳主命题", "challenges"),
        ("同行评议 + 反证/边界", "界定外推边界", "boundary"),
        ("测量平台", "提供观测与测量方法", "method"),
        ("同行评议", "支持候选 A 的机制", "supports"),
    ],
)
def test_source_relation_is_inferred_from_declared_role(
    source_type: str, contribution: str, expected: str
) -> None:
    assert exporter.infer_source_relation(source_type, contribution) == expected


def test_slice_fields_accepts_annotations_outside_bold_label() -> None:
    fields = exporter.slice_fields(
        """- **修订前**（候选 A）：旧命题。
- **修订后**（候选 A）：新命题。
""",
        ["修订前", "修订后"],
    )

    assert fields["修订前"] == ["旧命题。"]
    assert fields["修订后"] == ["新命题。"]


def test_extract_predictions_accepts_heading_then_body() -> None:
    body = """- **可检验预测 P1（定量）**：
  指标相对基线至少提高 10%。
"""

    assert exporter.extract_predictions(body) == ["指标相对基线至少提高 10%。"]


def test_parse_selection_accepts_backup_hypothesis_alias() -> None:
    selection = exporter.parse_selection(
        """- **主假说**：候选 A。
- **备份假说**：候选 B。
"""
    )

    assert selection["主假说"] == ["候选 A。"]
    assert selection["备份假说"] == ["候选 B。"]


def test_verification_status_requires_a_machine_resolvable_locator() -> None:
    assert (
        exporter.infer_verification_status("https://doi.org/10.1038/test")
        == "metadata_checked"
    )
    assert exporter.infer_verification_status(None) == "unverified"


def test_build_outputs_omits_agent_identity_and_external_source_path(
    tmp_path: Path,
) -> None:
    source = tmp_path / "SCI-001.md"
    source.write_text(
        """# SCI-001 高质量假说包

- 题目原文：Why test?
- 领域：test
- 完成时间：2026-09-06
- 执行 Agent：agent-private

## 1、题目复述与研究边界
**复述**：测试一个机制命题。

## 2、资料来源
| 编号 | 标题 | 作者/机构 | 年份 | 类型 | 链接/DOI | 关键贡献 |
|---|---|---|---|---|---|---|
| S1 | Paper | Author | 2024 | 同行评议 | https://doi.org/10.1000/test | 支持机制。 |

## 3、候选假说
### 候选 A：机制 A
- **陈述**：变量 X 通过机制 M 改变 Y。
- **机制**：X → M → Y。
- **证据指向**：S1。
- **风险**：可能存在替代解释 Z。
- **预测 P1**：X 改变时 Y 至少变化 10%。

### 候选 B：机制 B
- **陈述**：Z 独立改变 Y。
- **机制**：Z → Y。
- **证据指向**：S1。
- **风险**：效应可能为零。
- **预测 P1**：控制 Z 后 X 的效应消失。

## 4、七维评审
| 维度 | 候选 A | 候选 B | 说明 |
|---|---|---|---|
| 总分 | 30 | 26 | A 更强 |

## 5、反馈与修订
### 修订 1
- **修订触发**：反证检查
- **修订前**：X 改变 Y。
- **修订后**：仅在边界 K 内，X 通过 M 改变 Y。
- **为什么更好**：范围可证伪。

## 6、最终筛选
- **主假说**：候选 A
- **备选假说**：候选 B

## 7、主假说包
- **假说陈述**：仅在边界 K 内，X 通过 M 改变 Y。
- **可检验预测 P1**：X 改变时 Y 至少变化 10%。
- **证伪条件**：预注册检验显示变化小于 10%。
- **适用边界**：仅限 K。
- **不确定性声明**：Z 仍可能混杂。

## 8、研究计划
| 步骤 | 行动 | 数据/实验 | 判据 |
|---|---|---|---|
| 1 | 预注册对照 | 数据 D | 效应是否达到 10% |
""",
        encoding="utf-8",
    )

    markdown, projection, warnings, stats = exporter.build_outputs(
        "SCI-001", str(source), "Why test?", source.read_text(encoding="utf-8")
    )

    serialized = json.dumps(projection, ensure_ascii=False)
    assert "agent-private" not in markdown
    assert "agent-private" not in serialized
    assert "执行 Agent" not in markdown
    assert "附录：原始假说包全文" not in markdown
    assert "source_document" not in projection
    assert projection["status"] == "hypothesis_generation_complete"
    assert projection["workflow_completed"] is True
    assert projection["result_classification"]["expected_result"] is True
    assert stats["workflow_completed"] is True
    assert stats["scored_cands"] == 2
    assert stats["revisions"] == 1
    assert stats["predictions"] == 1
    assert stats["selection_complete"] is True
    assert stats["falsification_complete"] is True
    assert not warnings


def test_incomplete_revision_is_not_counted_as_substantive(tmp_path: Path) -> None:
    source = tmp_path / "SCI-001.md"
    source.write_text(
        """## 5、反馈与修订
- **修订触发**：只有触发说明。
""",
        encoding="utf-8",
    )

    _, _, _, stats = exporter.build_outputs(
        "SCI-001", str(source), "Question", source.read_text(encoding="utf-8")
    )

    assert stats["revisions"] == 0


def test_revision_aliases_are_counted_as_substantive(tmp_path: Path) -> None:
    source = tmp_path / "SCI-001.md"
    source.write_text(
        """## 5、反馈与修订
- 修订前：旧命题。
- 触发证据：边界来源 S4。
- 修订后：新命题。
- 实质影响：结论变为可证伪。
""",
        encoding="utf-8",
    )

    _, _, _, stats = exporter.build_outputs(
        "SCI-001", str(source), "Question", source.read_text(encoding="utf-8")
    )

    assert stats["revisions"] == 1


def test_public_export_omits_actual_experiment_metadata(tmp_path: Path) -> None:
    source = tmp_path / "SCI-096.md"
    source.write_text(
        """## 8、研究计划
### actual_experiment_result
- actual_execution_performed: true
- actual_experiment_status: inconclusive
- actual_experiment_decision: BRANCH
- actual_experiment_dataset: DANDI 000942
- actual_experiment_artifact_refs: evidence/SCI-096/result.json

## 10、论文摘要
- paper_abstract：DANDI 实验结果为 inconclusive，建议 BRANCH。
""",
        encoding="utf-8",
    )
    markdown, projection, _, stats = exporter.build_outputs(
        "SCI-096", str(source), "Question", source.read_text(encoding="utf-8")
    )

    serialized = json.dumps(projection, ensure_ascii=False)
    for forbidden in (
        "actual_experiment",
        "DANDI",
        "inconclusive",
        "BRANCH",
        "evidence/SCI-096",
    ):
        assert forbidden not in markdown
        assert forbidden not in serialized
    assert projection["result_classification"] == {
        "generated_hypothesis": True,
        "proposed_research_plan": True,
        "expected_result": True,
        "actual_execution_performed": False,
    }
    assert projection["competition_result_view"]["experiments"] == {
        "execution_mode": "proposed",
        "proposed_steps": 0,
    }
    assert projection["competition_result_view"]["results"] == {
        "classification": "expected",
        "status": "proposed",
        "decision": None,
        "summary": "本研究计划为待执行验证方案，未执行任何实验。",
        "artifact_refs": ["summaries/SCI-096.md"],
    }
    assert "actual_experiment" not in stats
