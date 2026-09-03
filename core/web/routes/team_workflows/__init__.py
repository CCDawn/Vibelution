"""Team workflow routes package (Clarity P5/B1)."""
from __future__ import annotations

from . import challenge_cup_dev_controls as _challenge_cup_dev_controls  # noqa: F401
from . import challenge_cup_real_batch as _challenge_cup_real_batch  # noqa: F401
from . import experiment as _experiment  # noqa: F401
from . import g12_calibration as _g12_calibration  # noqa: F401
from . import hypothesis_first as _hypothesis_first  # noqa: F401
from . import knowledge as _knowledge  # noqa: F401
from . import orchestration as _orchestration  # noqa: F401
from . import research_ops as _research_ops  # noqa: F401
from . import research_projects as _research_projects  # noqa: F401
from . import research_runtime as _research_runtime  # noqa: F401
from . import research_templates as _research_templates  # noqa: F401
from . import source_collection as _source_collection  # noqa: F401
from . import stage_rounds as _stage_rounds  # noqa: F401
from ._router import router

__all__ = ["router"]
