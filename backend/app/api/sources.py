from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.common import map_repository_error
from app.core.auth import CurrentUser
from app.core.repository import Repository

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("/{document_id}/chunks/{chunk_id}")
async def get_source(
    document_id: UUID,
    chunk_id: UUID,
    user: CurrentUser,
    repository: Repository,
) -> dict:
    try:
        return await repository.get_global_source(document_id, chunk_id)
    except Exception as exc:
        raise map_repository_error(exc) from None
