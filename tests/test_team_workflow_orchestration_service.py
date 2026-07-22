"""Team workflow orchestration service tests (aggregate entry).

Implementation lives under ``tests/_support/team_workflow/``:

- ``helpers.py`` — shared fakes/fixtures
- ``cases_structure.py``
- ``cases_source_collection.py``
- ``cases_experiment.py``
- ``cases_research_knowledge.py``
- ``cases_remainder.py``

This module re-exports every case so selectors/docs that reference
``tests/test_team_workflow_orchestration_service.py`` keep working without
double-collecting when the full suite runs.

Run one domain without loading others::

    py -3 -m pytest tests/_support/team_workflow/cases_source_collection.py -q

(Pytest collects an explicit path even though the filename does not match
``test_*.py``.)
"""
from __future__ import annotations

from tests._support.team_workflow.cases_structure import *  # noqa: F403
from tests._support.team_workflow.cases_source_collection import *  # noqa: F403
from tests._support.team_workflow.cases_experiment import *  # noqa: F403
from tests._support.team_workflow.cases_research_knowledge import *  # noqa: F403
from tests._support.team_workflow.cases_remainder import *  # noqa: F403
