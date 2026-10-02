from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, Field, field_validator

from app.api.common import map_repository_error, page_payload, parsed_cursor
from app.core.auth import CurrentUser
from app.core.repository import Repository

router = APIRouter(prefix="/conversations", tags=["conversations"])


class ConversationCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    case_id: UUID | None = None
    domain: Literal["labour_law"] = "labour_law"

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title cannot be blank")
        return value


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    case_id: UUID | None = None

    @field_validator("title")
    @classmethod
    def strip_optional_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("title cannot be blank")
        return value


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate, user: CurrentUser, repository: Repository
) -> dict:
    try:
        return await repository.create_conversation(
            user.id,
            title=payload.title,
            domain_code=payload.domain,
            case_id=payload.case_id,
        )
    except Exception as exc:
        raise map_repository_error(exc) from None


@router.get("")
async def list_conversations(
    user: CurrentUser,
    repository: Repository,
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, max_length=500),
    case_id: UUID | None = None,
) -> dict:
    try:
        page = await repository.list_conversations(
            user.id,
            limit=limit,
            cursor=parsed_cursor(cursor),
            case_id=case_id,
        )
        return page_payload(page)
    except Exception as exc:
        raise map_repository_error(exc) from None


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: UUID, user: CurrentUser, repository: Repository
) -> dict:
    try:
        return await repository.get_conversation(user.id, conversation_id)
    except Exception as exc:
        raise map_repository_error(exc) from None


@router.patch("/{conversation_id}")
async def update_conversation(
    conversation_id: UUID,
    payload: ConversationUpdate,
    user: CurrentUser,
    repository: Repository,
) -> dict:
    try:
        return await repository.update_conversation(
            user.id,
            conversation_id,
            title=payload.title,
            case_id=payload.case_id,
            case_id_set="case_id" in payload.model_fields_set,
        )
    except Exception as exc:
        raise map_repository_error(exc) from None


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: UUID, user: CurrentUser, repository: Repository
) -> Response:
    try:
        await repository.delete_conversation(user.id, conversation_id)
    except Exception as exc:
        raise map_repository_error(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{conversation_id}/messages")
async def list_messages(
    conversation_id: UUID,
    user: CurrentUser,
    repository: Repository,
    limit: int = Query(default=50, ge=1, le=50),
    cursor: str | None = Query(default=None, max_length=500),
) -> dict:
    try:
        page = await repository.list_messages(
            user.id,
            conversation_id,
            limit=limit,
            cursor=parsed_cursor(cursor),
        )
        return page_payload(page)
    except Exception as exc:
        raise map_repository_error(exc) from None
