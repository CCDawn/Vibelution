from core.logging import console_logger, debug
from core.logging.logger import DebugLogger


def test_logging_package_exports_debug_compat_alias():
    assert isinstance(debug, DebugLogger)
    assert console_logger is debug
