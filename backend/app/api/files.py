from __future__ import annotations

import re
import unicodedata
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.api.common import map_repository_error
from app.core.auth import CurrentUser
from app.core.config import Settings, get_settings
from app.core.repository import ConflictError, Repository
from app.core.storage import StorageError, SupabaseStorage, get_storage

router = APIRouter(tags=["files"])


class UploadIntentRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    media_type: Literal["application/pdf", "text/plain"]
    size_bytes: int = Field(ge=1)

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        value = value.strip()
        if not value or "/" in value or "\\" in value or "\x00" in value:
            raise ValueError("invalid filename")
        return value


def _safe_storage_name(filename: str, media_type: str) -> str:
    expected = ".pdf" if media_type == "application/pdf" else ".txt"
    stem = filename.rsplit(".", 1)[0]
    ascii_stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_stem).strip("-._")[:100]
    slug = re.sub(r"-{2,}", "-", slug)
    return f"{slug or 'document'}{expected}"


@router.post("/cases/{case_id}/files/upload-intent", status_code=status.HTTP_201_CREATED)
async def upload_intent(
    case_id: UUID,
    payload: UploadIntentRequest,
    user: CurrentUser,
    repository: Repository,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    if payload.size_bytes > settings.case_file_max_bytes:
        raise HTTPException(status_code=413, detail={"code": "file_too_large"})
    try:
        file = await repository.create_file_intent(
            user.id,
            case_id=case_id,
            original_name=payload.filename,
            safe_name=_safe_storage_name(payload.filename, payload.media_type),
            media_type=payload.media_type,
            size_bytes=payload.size_bytes,
            reservation_bytes=settings.case_file_max_bytes,
            bucket=settings.case_files_bucket,
            quota_bytes=settings.user_file_quota_bytes,
        )
    except Exception as exc:
        raise map_repository_error(exc) from None
    return {
        "file": file,
        "upload": {
            "bucket": file["storage_bucket"],
            "path": file["storage_path"],
            "upsert": False,
            "authorization": "supabase_user_jwt",
        },
    }


@router.post("/files/{file_id}/complete", status_code=status.HTTP_202_ACCEPTED)
async def complete_file(file_id: UUID, user: CurrentUser, repository: Repository) -> dict:
    try:
        return await repository.complete_file(user.id, file_id)
    except Exception as exc:
        raise map_repository_error(exc) from None


@router.get("/files/{file_id}/status")
async def file_status(file_id: UUID, user: CurrentUser, repository: Repository) -> dict:
    try:
        return await repository.get_file(user.id, file_id)
    except Exception as exc:
        raise map_repository_error(exc) from None


@router.get("/cases/{case_id}/files")
async def list_files(case_id: UUID, user: CurrentUser, repository: Repository) -> dict:
    try:
        return {"items": await repository.list_files(user.id, case_id)}
    except Exception as exc:
        raise map_repository_error(exc) from None


@router.post("/files/{file_id}/download-url")
async def download_url(
    file_id: UUID,
    user: CurrentUser,
    repository: Repository,
    storage: Annotated[SupabaseStorage, Depends(get_storage)],
) -> dict:
    try:
        file = await repository.get_file(user.id, file_id)
        if file["status"] != "uploaded":
            raise ConflictError("file_not_ready")
        return {"url": await storage.signed_download_url(file["storage_path"], expires=60)}
    except Exception as exc:
        if isinstance(exc, StorageError):
            raise HTTPException(
                status_code=503, detail={"code": "storage_temporarily_unavailable"}
            ) from None
        raise map_repository_error(exc) from None


@router.delete("/files/{file_id}", status_code=status.HTTP_202_ACCEPTED)
async def delete_file(file_id: UUID, user: CurrentUser, repository: Repository) -> dict:
    try:
        return await repository.request_file_deletion(user.id, file_id)
    except Exception as exc:
        raise map_repository_error(exc) from None
