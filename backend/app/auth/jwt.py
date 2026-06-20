"""Supabase JWT validation for FastAPI — JWKS approach.

Validates the Supabase access token sent by the frontend as a Bearer token in the
Authorization header. Modern Supabase projects sign tokens with ES256 (ECDSA) keys
served via a JWKS endpoint. The project ref is extracted from the token's ``iss``
claim, so no additional configuration is needed.

Falls back to HMAC (HS256) validation if the legacy SUPABASE_JWT_SECRET is
configured, for backward compatibility with older Supabase projects.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Annotated
from urllib.parse import urlparse

import httpx
from fastapi import Header
from jwt import PyJWK, get_unverified_header
from jwt import decode as jwt_decode
from jwt.exceptions import PyJWTError

from app.config import get_settings

_ACCEPTED_ALGORITHMS: set[str] = {"ES256", "RS256"}
_JWKS_CACHE_TTL = 3600  # Cache JWKS public keys for 1 hour

# Module-level JWKS cache: project_ref -> (keys_list, fetched_at_timestamp)
_jwks_cache: dict[str, tuple[list[dict], float]] = {}


@dataclass(frozen=True, slots=True)
class AuthUser:
    """Represents an authenticated user extracted from a valid Supabase JWT."""

    id: str  # The Supabase user UUID ("sub" claim)
    email: str | None = None


_AUDIENCE = "authenticated"


def _extract_project_ref(iss: str) -> str | None:
    """Extract the Supabase project ref from the JWT issuer claim.

    The ``iss`` claim looks like: https://<project-ref>.supabase.co/auth/v1
    Returns the subdomain (project-ref) or None if it doesn't match.
    """
    try:
        parsed = urlparse(iss)
        hostname = parsed.hostname or ""
        if not hostname.endswith(".supabase.co"):
            return None
        return hostname.split(".")[0]
    except (ValueError, AttributeError):
        return None


async def _fetch_jwks(project_ref: str) -> list[dict] | None:
    """Fetch and cache the JWKS from Supabase's public endpoint.

    Cached for ``_JWKS_CACHE_TTL`` seconds. Returns cached keys if a fetch
    fails, or None if the cache is empty and the fetch fails.
    """
    now = time.monotonic()
    cached_keys, cached_at = _jwks_cache.get(project_ref, ([], 0.0))
    if cached_keys and (now - cached_at) < _JWKS_CACHE_TTL:
        return cached_keys

    url = f"https://{project_ref}.supabase.co/auth/v1/.well-known/jwks.json"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            keys = data.get("keys", [])
            _jwks_cache[project_ref] = (keys, now)
            return keys
    except Exception:  # noqa: BLE001
        return cached_keys or None


async def _validate_token_jwks(token: str) -> AuthUser | None:
    """Validate a Supabase JWT using JWKS (ES256 / RS256)."""
    try:
        unverified_header = get_unverified_header(token)
        unverified_payload = jwt_decode(
            token, options={"verify_signature": False, "verify_exp": False, "verify_aud": False}
        )
    except PyJWTError:
        return None

    kid = unverified_header.get("kid")
    alg = unverified_header.get("alg", "")
    iss = unverified_payload.get("iss", "")

    # Reject algorithms we don't expect from Supabase.
    if alg not in _ACCEPTED_ALGORITHMS:
        return None

    # Extract the project ref from the token's issuer claim.
    project_ref = _extract_project_ref(iss)
    if not project_ref:
        return None

    # Fetch JWKS (cached).
    keys = await _fetch_jwks(project_ref)
    if not keys:
        return None

    # Find the specific key identified by the token's kid.
    key_data = next((k for k in keys if k.get("kid") == kid), None)
    if not key_data:
        return None

    try:
        jwk = PyJWK(key_data)
        verified = jwt_decode(token, jwk.key, algorithms=[alg], audience=_AUDIENCE)
        user_id = verified.get("sub")
        if not user_id:
            return None
        return AuthUser(id=user_id, email=verified.get("email"))
    except PyJWTError:
        return None


def _validate_token_hmac(token: str, secret: str) -> AuthUser | None:
    """Validate a Supabase JWT using the legacy HMAC shared secret (HS256).

    Uses PyJWT's decode() which accepts both string secrets and key objects.
    """
    try:
        payload = jwt_decode(token, secret, algorithms=["HS256"], audience=_AUDIENCE)
        user_id = payload.get("sub")
        if not user_id:
            return None
        return AuthUser(id=user_id, email=payload.get("email"))
    except PyJWTError:
        return None


async def get_optional_user(
    authorization: Annotated[str | None, Header(include_in_schema=False)] = None,
) -> AuthUser | None:
    """FastAPI dependency: extract and validate the Supabase JWT, or return None.

    Tries JWKS first (modern Supabase — ES256/RS256), then falls back to HMAC
    (legacy Supabase — HS256) if ``SUPABASE_JWT_SECRET`` is configured.

    Anonymous requests (no header or invalid token) are not rejected — they
    simply get ``None``. This is the intended design: Cartograph is
    anonymous-friendly.
    """
    if not authorization:
        return None
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        return None

    # 1. Try JWKS (modern Supabase — ES256/RS256).
    user = await _validate_token_jwks(token)
    if user is not None:
        return user

    # 2. Fall back to HMAC (legacy Supabase — HS256).
    settings = get_settings()
    if settings.supabase_jwt_secret:
        user = _validate_token_hmac(token, settings.supabase_jwt_secret)
        if user is not None:
            return user

    return None
