from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.common import map_repository_error
from app.core.auth import CurrentUser
from app.core.config import Settings, get_settings
from app.core.repository import Repository

router = APIRouter(prefix="/me", tags=["me"])


@router.post("/bootstrap")
async def bootstrap(user: CurrentUser, repository: Repository) -> dict:
    try:
        return await repository.bootstrap(user.id, user.email)
    except Exception as exc:
        raise map_repository_error(exc) from None


@router.get("")
async def me(user: CurrentUser, repository: Repository) -> dict:
    try:
        return await repository.get_me(user.id, user.email)
    except Exception as exc:
        raise map_repository_error(exc) from None


@router.get("/workspace")
async def workspace(user: CurrentUser, repository: Repository) -> dict:
    try:
        return await repository.get_workspace(user.id)
    except Exception as exc:
        raise map_repository_error(exc) from None


@router.get("/storage")
async def storage(
    user: CurrentUser,
    repository: Repository,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """How much of the file quota the user's cases and chats use."""
    try:
        used = await repository.file_storage_bytes(user.id)
    except Exception as exc:
        raise map_repository_error(exc) from None
    return {"used_bytes": used, "quota_bytes": settings.user_file_quota_bytes}
