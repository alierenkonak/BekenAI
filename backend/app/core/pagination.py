from __future__ import annotations

import base64
import json
from datetime import datetime
from uuid import UUID


def encode_cursor(created_at: datetime, item_id: UUID) -> str:
    payload = json.dumps(
        {"created_at": created_at.isoformat(), "id": str(item_id)},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_cursor(value: str | None) -> tuple[datetime, UUID] | None:
    if not value:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        return datetime.fromisoformat(payload["created_at"]), UUID(payload["id"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_cursor") from exc
