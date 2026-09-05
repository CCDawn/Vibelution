"""One revision observation for one batch of UI command offers."""

from collections.abc import Mapping
from typing import Any

from ..readiness.common import DomainReadinessContext


class OfferRevisionContext:
    """Delegate live domain reads; reuse only this batch's revision vector.

    Created per offer build, never installed on the command execution context.
    A subsequent snapshot therefore observes settlements and source changes.
    """

    def __init__(self, source: DomainReadinessContext) -> None:
        self._source = source
        self._revisions: dict[tuple[str, str], dict[str, str]] = {}

    def domain_revision_vector(self, team_id: str, run_id: str) -> Mapping[str, str]:
        key = (team_id, run_id)
        if key not in self._revisions:
            self._revisions[key] = dict(self._source.domain_revision_vector(team_id, run_id))
        return dict(self._revisions[key])

    def __getattr__(self, name: str) -> Any:
        return getattr(self._source, name)
