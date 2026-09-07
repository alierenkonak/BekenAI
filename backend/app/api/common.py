from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.core.pagination import decode_cursor, encode_cursor
from app.core.repository import ConflictError, NotFoundError, Page


def parsed_cursor(value: str | None) -> tuple[datetime, UUID] | None:
    try:
        return decode_cursor(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_cursor"},
        ) from None


def page_payload(page: Page) -> dict[str, Any]:
    next_cursor = None
    if page.next_cursor:
        next_cursor = encode_cursor(*page.next_cursor)
    return {"items": page.items, "next_cursor": next_cursor}


def map_repository_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=404, detail={"code": str(exc)})
    if isinstance(exc, ConflictError):
        return HTTPException(status_code=409, detail={"code": str(exc)})
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "data_service_unavailable"},
    )
