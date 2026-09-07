from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings

_bearer = HTTPBearer(auto_error=False)
_ALLOWED_ASYMMETRIC_ALGORITHMS = {"RS256", "ES256", "EdDSA"}


@dataclass(frozen=True)
class AuthenticatedUser:
    id: UUID
    email: str | None = None


class SupabaseTokenVerifier:
    def __init__(self, settings: Settings) -> None:
        if not settings.supabase_url:
            raise ValueError("SUPABASE_URL is required")
        parts = urlsplit(settings.supabase_url)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise ValueError("SUPABASE_URL must be an absolute HTTPS URL without credentials")
        self.settings = settings
        self.base_url = settings.supabase_url.rstrip("/")
        self.issuer = f"{self.base_url}/auth/v1"
        self.jwks = jwt.PyJWKClient(
            f"{self.issuer}/.well-known/jwks.json",
            cache_jwk_set=True,
            lifespan=600,
        )

    async def verify(self, token: str) -> AuthenticatedUser:
        try:
            header = jwt.get_unverified_header(token)
            algorithm = str(header.get("alg") or "")
        except jwt.PyJWTError as exc:
            raise ValueError("invalid_token") from exc
        if algorithm in _ALLOWED_ASYMMETRIC_ALGORITHMS:
            try:
                claims = await asyncio.to_thread(self._verify_asymmetric, token, algorithm)
            except jwt.PyJWTError as exc:
                raise ValueError("invalid_token") from exc
        else:
            claims = await self._verify_with_auth_server(token)
        try:
            user_id = UUID(str(claims["sub"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid_subject") from exc
        role = claims.get("role")
        if role != "authenticated":
            raise ValueError("invalid_role")
        email = claims.get("email")
        return AuthenticatedUser(id=user_id, email=str(email) if email else None)

    def _verify_asymmetric(self, token: str, algorithm: str) -> dict:
        signing_key = self.jwks.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=[algorithm],
            audience="authenticated",
            issuer=self.issuer,
            options={"require": ["exp", "iss", "sub", "role"]},
        )

    async def _verify_with_auth_server(self, token: str) -> dict:
        headers = {
            "apikey": self.settings.supabase_publishable_secret,
            "Authorization": f"Bearer {token}",
        }
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(5.0),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.get("/auth/v1/user", headers=headers)
        if response.status_code != 200:
            raise ValueError("invalid_token")
        payload = response.json()
        return {
            "sub": payload.get("id"),
            "email": payload.get("email"),
            "role": payload.get("role") or "authenticated",
        }


@lru_cache
def get_token_verifier() -> SupabaseTokenVerifier:
    return SupabaseTokenVerifier(get_settings())


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "authentication_required"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    verifier = get_token_verifier()
    try:
        return await verifier.verify(credentials.credentials)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_access_token"},
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
