from app.api.common import map_repository_error
from app.core.repository import CapacityExceededError


def test_capacity_error_maps_to_retryable_http_429() -> None:
    error = map_repository_error(CapacityExceededError("chat_capacity_exceeded"))

    assert error.status_code == 429
    assert error.detail == {"code": "chat_capacity_exceeded"}
    assert error.headers == {"Retry-After": "10"}
