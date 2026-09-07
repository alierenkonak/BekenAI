from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.auth import SupabaseTokenVerifier, get_current_user
from app.core.config import Settings
from app.main import app


class StaticJwks:
    def __init__(self, key) -> None:
        self.key = key

    def get_signing_key_from_jwt(self, _token: str):
        return type("SigningKey", (), {"key": self.key})()


def settings() -> Settings:
    return Settings(
        _env_file=None,
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="sb_publishable_test",
    )


def token(*, issuer: str, expires: datetime) -> tuple[str, object]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    payload = {
        "sub": "11111111-1111-1111-1111-111111111111",
        "role": "authenticated",
        "aud": "authenticated",
        "iss": issuer,
        "exp": expires,
    }
    encoded = jwt.encode(payload, private, algorithm="RS256", headers={"kid": "test"})
    return encoded, private.public_key()


@pytest.mark.asyncio
async def test_verifier_accepts_valid_supabase_jwt() -> None:
    verifier = SupabaseTokenVerifier(settings())
    encoded, public = token(
        issuer=verifier.issuer, expires=datetime.now(UTC) + timedelta(minutes=5)
    )
    verifier.jwks = StaticJwks(public)
    user = await verifier.verify(encoded)
    assert user.id == UUID("11111111-1111-1111-1111-111111111111")


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_kind", ["issuer", "expired"])
async def test_verifier_rejects_wrong_issuer_and_expired_token(bad_kind: str) -> None:
    verifier = SupabaseTokenVerifier(settings())
    issuer = "https://attacker.invalid/auth/v1" if bad_kind == "issuer" else verifier.issuer
    expires = datetime.now(UTC) + (
        timedelta(minutes=-5) if bad_kind == "expired" else timedelta(minutes=5)
    )
    encoded, public = token(issuer=issuer, expires=expires)
    verifier.jwks = StaticJwks(public)
    with pytest.raises(ValueError):
        await verifier.verify(encoded)


@pytest.mark.asyncio
async def test_search_requires_authentication() -> None:
    override = app.dependency_overrides.pop(get_current_user)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post("/search", json={"query": "fesih bildirimi"})
    finally:
        app.dependency_overrides[get_current_user] = override
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "authentication_required"
