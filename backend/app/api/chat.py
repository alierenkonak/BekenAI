from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from pydantic import BaseModel, Field, field_validator

from app.api.common import map_repository_error
from app.chat.query import derive_retrieval_query
from app.core.auth import CurrentUser
from app.core.config import Settings, get_settings
from app.core.repository import Repository

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    conversation_id: UUID | None = None
    case_id: UUID | None = None
    # Room for a pasted fact pattern; whole documents belong in an uploaded file.
    message: str = Field(min_length=3, max_length=4000)
    domain: Literal["labour_law"] = "labour_law"
    include_doctrine: bool = False

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("message must contain at least 3 non-whitespace characters")
        return value


@router.post("/chat", status_code=status.HTTP_202_ACCEPTED)
async def enqueue_chat(
    payload: ChatRequest,
    user: CurrentUser,
    repository: Repository,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=180),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    try:
        return await repository.enqueue_chat(
            user.id,
            idempotency_key=idempotency_key,
            conversation_id=payload.conversation_id,
            case_id=payload.case_id,
            message=payload.message,
            domain_code=payload.domain,
            include_doctrine=payload.include_doctrine,
            retrieval_query=derive_retrieval_query(payload.message),
            requested_model=settings.gemini_primary_model,
            max_active_jobs=settings.chat_max_active_jobs,
        )
    except Exception as exc:
        raise map_repository_error(exc) from None


@router.get("/chat/generations/{generation_id}")
async def get_generation(generation_id: UUID, user: CurrentUser, repository: Repository) -> dict:
    try:
        return await repository.get_generation(user.id, generation_id)
    except Exception as exc:
        raise map_repository_error(exc) from None


@router.post("/chat/generations/{generation_id}/cancel")
async def cancel_generation(generation_id: UUID, user: CurrentUser, repository: Repository) -> dict:
    try:
        return await repository.cancel_generation(user.id, generation_id)
    except Exception as exc:
        raise map_repository_error(exc) from None
