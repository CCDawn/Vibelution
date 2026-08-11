from core.logging import debug
from core.logging.logger import DebugLogger


def test_logging_package_exports_debug_compat_alias():
    assert isinstance(debug, DebugLogger)


def test_debug_logger_matches_logger_package_alias():
    from core.logging import debug_logger

    assert debug_logger is debug
