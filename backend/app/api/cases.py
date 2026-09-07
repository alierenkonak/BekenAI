from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, Field, field_validator

from app.api.common import map_repository_error, page_payload, parsed_cursor
from app.core.auth import CurrentUser
from app.core.repository import Repository

router = APIRouter(prefix="/cases", tags=["cases"])


class CaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value


class CaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def strip_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_case(payload: CaseCreate, user: CurrentUser, repository: Repository) -> dict:
    try:
        return await repository.create_case(user.id, payload.name, payload.description)
    except Exception as exc:
        raise map_repository_error(exc) from None


@router.get("")
async def list_cases(
    user: CurrentUser,
    repository: Repository,
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, max_length=500),
) -> dict:
    try:
        page = await repository.list_cases(user.id, limit=limit, cursor=parsed_cursor(cursor))
        return page_payload(page)
    except Exception as exc:
        raise map_repository_error(exc) from None


@router.get("/{case_id}")
async def get_case(case_id: UUID, user: CurrentUser, repository: Repository) -> dict:
    try:
        return await repository.get_case(user.id, case_id)
    except Exception as exc:
        raise map_repository_error(exc) from None


@router.patch("/{case_id}")
async def update_case(
    case_id: UUID, payload: CaseUpdate, user: CurrentUser, repository: Repository
) -> dict:
    fields = payload.model_fields_set
    try:
        return await repository.update_case(
            user.id,
            case_id,
            name=payload.name,
            description=payload.description,
            description_set="description" in fields,
        )
    except Exception as exc:
        raise map_repository_error(exc) from None


@router.delete("/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_case(case_id: UUID, user: CurrentUser, repository: Repository) -> Response:
    try:
        await repository.delete_case(user.id, case_id)
    except Exception as exc:
        raise map_repository_error(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
