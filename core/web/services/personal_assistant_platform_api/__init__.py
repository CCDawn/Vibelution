"""Personal-assistant read-only loopback platform API pack."""

from core.web.services.personal_assistant_platform_api.api import (
    platform_api_get,
    platform_api_index,
)

__all__ = ["platform_api_get", "platform_api_index"]
