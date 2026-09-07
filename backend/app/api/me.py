from __future__ import annotations

from fastapi import APIRouter

from app.api.common import map_repository_error
from app.core.auth import CurrentUser
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
