"""Unit tests for source-collection stage advance hard gate."""

from __future__ import annotations

import unittest
from unittest import mock


class StageAdvanceReadyTests(unittest.TestCase):
    def test_ingestion_blocked_when_graph_has_nodes_but_no_edges(self) -> None:
        from core.web.services.team_workflow.source_collection import stages

        class FakeService:
            class TeamWorkflowOrchestrationError(Exception):
                pass

            def _normalize_source_collection_stage_id(self, value, default=""):
                return value or default

        with mock.patch.object(stages, "_service", return_value=FakeService()):
            with self.assertRaises(FakeService.TeamWorkflowOrchestrationError) as ctx:
                stages.assert_source_collection_stage_advance_ready(
                    stage_id="ingestion",
                    record_count=19,
                    approved_or_source_candidate_count=19,
                    graph_node_count=19,
                    graph_edge_count=0,
                    graph_missing_link_count=36,
                )
        self.assertIn("推进失败（不合格）", str(ctx.exception))
        self.assertIn("0 条边", str(ctx.exception))

    def test_ingestion_allowed_when_graph_healthy(self) -> None:
        from core.web.services.team_workflow.source_collection import stages

        class FakeService:
            class TeamWorkflowOrchestrationError(Exception):
                pass

            def _normalize_source_collection_stage_id(self, value, default=""):
                return value or default

        with mock.patch.object(stages, "_service", return_value=FakeService()):
            stages.assert_source_collection_stage_advance_ready(
                stage_id="ingestion",
                record_count=19,
                approved_or_source_candidate_count=19,
                graph_node_count=19,
                graph_edge_count=18,
                graph_missing_link_count=2,
            )


if __name__ == "__main__":
    unittest.main()
