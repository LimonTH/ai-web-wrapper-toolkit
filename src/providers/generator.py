import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import jwt, JWTError

from src.core.config import settings

"""
Virtual API Key Generator.
Generates keys in the format wsk_live_xxxxxxxxxxxxxxxxxxxx
and encodes template data + cookie profile into JWT.
"""


def _generate_key_value(prefix: str = "wsk") -> str:
    """Generates a key in the format wsk_live_<32 hex chars>."""
    random_part = secrets.token_hex(16)
    return f"{prefix}_live_{random_part}"


def _build_jwt_payload(
        key_id: str,
        template_id: str,
        template_name: str,
        capabilities: list[str],
        cookie_profile_id: str | None = None,
        config_overrides: dict | None = None,
        expires_at: datetime | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": key_id,
        "iss": "ai-web-wrapper-toolkit",
        "iat": now,
        "template_id": template_id,
        "template_name": template_name,
        "capabilities": capabilities,
    }

    if cookie_profile_id:
        payload["cookie_profile_id"] = cookie_profile_id

    if config_overrides:
        payload["config_overrides"] = config_overrides

    if expires_at:
        payload["exp"] = expires_at
    else:
        payload["exp"] = now + timedelta(days=365)

    return payload


def generate_virtual_key(
        template_id: str,
        template_name: str,
        capabilities: list[str],
        cookie_profile_id: str | None = None,
        config_overrides: dict | None = None,
        expires_at: datetime | None = None,
        key_prefix: str = "wsk",
) -> dict[str, str]:
    """
    Generates a virtual API key.

    Returns:
        {"key_value": "wsk_live_abc123...", "jwt_token": "eyJhbGci..."}
    """
    key_id = str(uuid.uuid4())
    key_value = _generate_key_value(prefix=key_prefix)

    payload = _build_jwt_payload(
        key_id=key_id,
        template_id=template_id,
        template_name=template_name,
        capabilities=capabilities,
        cookie_profile_id=cookie_profile_id,
        config_overrides=config_overrides,
        expires_at=expires_at,
    )

    jwt_token = jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    return {
        "key_value": key_value,
        "jwt_token": jwt_token,
    }


def decode_virtual_key(jwt_token: str) -> dict[str, Any] | None:
    """Decodes a JWT. Returns the payload or None if the key is invalid/expired."""
    try:
        payload = jwt.decode(
            jwt_token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except JWTError:
        return None
