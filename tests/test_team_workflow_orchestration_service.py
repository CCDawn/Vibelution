"""Team workflow orchestration service tests — compatibility aggregate entry.

Domain packs (preferred for ``pytest-xdist --dist loadfile``)::

- ``test_team_workflow_structure_cases.py``
- ``test_team_workflow_source_collection_cases.py``
- ``test_team_workflow_experiment_cases.py``
- ``test_team_workflow_research_knowledge_cases.py``
- ``test_team_workflow_remainder_cases.py``

Case implementations live under ``tests/_support/team_workflow/``.

When this file is the **only** team-workflow case collector in the invocation
(e.g. historical docs still pass this path), it re-exports every domain so the
full behavioral suite still runs.

When the full ``tests/`` tree or any domain pack is also collected,
``conftest.pytest_ignore_collect`` skips this aggregate to avoid double-collection.

Run one domain::

    py -3 -m pytest tests/test_team_workflow_source_collection_cases.py -q

Or the legacy aggregate path (still works alone)::

    py -3 -m pytest tests/test_team_workflow_orchestration_service.py -q
"""
from __future__ import annotations

from tests._support.team_workflow.cases_structure import *  # noqa: F403
from tests._support.team_workflow.cases_source_collection import *  # noqa: F403
from tests._support.team_workflow.cases_experiment import *  # noqa: F403
from tests._support.team_workflow.cases_research_knowledge import *  # noqa: F403
from tests._support.team_workflow.cases_remainder import *  # noqa: F403
