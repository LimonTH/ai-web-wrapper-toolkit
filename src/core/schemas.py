from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


def _validate_url(v: str | None) -> str | None:
    """Validate URL is http/https and not a path traversal or file://."""
    if v is None:
        return v
    if not v.strip():
        raise ValueError("URL must not be empty")
    parsed = urlparse(v)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL scheme must be http or https")
    if not parsed.netloc:
        raise ValueError("URL must have a hostname")
    return v.rstrip("/")


_ALLOWED_AUTH = frozenset({"cookie", "token", "basic", "oauth", "none"})


class WebsiteTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    base_url: str = Field(..., min_length=1)
    icon_url: str | None = None
    auth_type: str = "cookie"
    default_headers: dict[str, str] | None = None

    @field_validator("base_url", "icon_url", mode="after")
    @classmethod
    def validate_urls(cls, v: str | None) -> str | None:
        return _validate_url(v)

    @field_validator("auth_type")
    @classmethod
    def validate_auth_type(cls, v: str) -> str:
        if v not in _ALLOWED_AUTH:
            raise ValueError(f"auth_type must be one of {_ALLOWED_AUTH}")
        return v


class WebsiteTemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    base_url: str | None = None
    icon_url: str | None = None
    auth_type: str | None = None
    capabilities: list[str] | None = None
    default_headers: dict[str, str] | None = None
    is_active: bool | None = None

    @field_validator("base_url", "icon_url", mode="after")
    @classmethod
    def validate_urls(cls, v: str | None) -> str | None:
        return _validate_url(v)

    @field_validator("auth_type")
    @classmethod
    def validate_auth_type(cls, v: str | None) -> str | None:
        if v is not None and v not in _ALLOWED_AUTH:
            raise ValueError(f"auth_type must be one of {_ALLOWED_AUTH}")
        return v


class WebsiteTemplateRead(BaseModel):
    id: str
    name: str
    description: str | None
    base_url: str
    icon_url: str | None
    auth_type: str
    capabilities: list[str]
    default_headers: dict | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApiEndpointCreate(BaseModel):
    template_id: str | None = None  # can be passed from URL
    functional_block: str = Field(
        ...,
        pattern=r"^(chat|projects|skills|image_gen|files|tools|search|code|embeddings|tts|stt|vision|reasoning|web_search|artifacts|memory)$",
    )
    label: str = Field(..., min_length=1)
    method: str = Field(..., pattern=r"^(GET|POST|PUT|DELETE|PATCH)$")
    path: str = Field(..., min_length=1)
    headers_template: dict[str, str] | None = None
    query_params_template: dict[str, str] | None = None
    body_template: dict[str, Any] | None = None
    response_schema: dict[str, Any] | None = None
    is_streaming: bool = False
    stream_event_field: str | None = None
    order: int = 0


class ApiEndpointUpdate(BaseModel):
    functional_block: str | None = None
    label: str | None = None
    method: str | None = None
    path: str | None = None
    headers_template: dict[str, str] | None = None
    query_params_template: dict[str, str] | None = None
    body_template: dict[str, Any] | None = None
    response_schema: dict[str, Any] | None = None
    is_streaming: bool | None = None
    stream_event_field: str | None = None
    order: int | None = None


class ApiEndpointRead(BaseModel):
    id: str
    template_id: str
    functional_block: str
    label: str
    method: str
    path: str
    headers_template: dict | None
    query_params_template: dict | None
    body_template: dict | None
    response_schema: dict | None
    is_streaming: bool
    stream_event_field: str | None
    order: int
    created_at: datetime

    model_config = {"from_attributes": True}


class CookieProfileCreate(BaseModel):
    template_id: str
    name: str = Field(..., min_length=1)
    description: str | None = None
    cookies: list[dict[str, Any]] = Field(default_factory=list)
    extra_headers: dict[str, str] | None = None
    storage_state: dict[str, Any] | None = None


class CookieProfileUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    cookies: list[dict[str, Any]] | None = None
    extra_headers: dict[str, str] | None = None
    storage_state: dict[str, Any] | None = None
    is_active: bool | None = None


class CookieProfileRead(BaseModel):
    id: str
    template_id: str
    name: str
    description: str | None
    cookies: list[dict[str, Any]]
    extra_headers: dict | None
    storage_state: dict | None
    is_active: bool
    last_used_at: datetime | None
    created_at: datetime
    expires_at: datetime | None

    model_config = {"from_attributes": True}


class VirtualApiKeyCreate(BaseModel):
    template_id: str
    cookie_profile_id: str | None = None
    name: str = Field(..., min_length=1)
    config_overrides: dict[str, Any] | None = None
    expires_at: datetime | None = None


class VirtualApiKeyRead(BaseModel):
    id: str
    template_id: str
    cookie_profile_id: str | None
    name: str
    key_value: str
    key_prefix: str
    jwt_token: str | None
    config_overrides: dict | None
    is_active: bool
    last_used_at: datetime | None
    expires_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ActionRecordingCreate(BaseModel):
    template_id: str
    cookie_profile_id: str | None = None


class ActionRecordingRead(BaseModel):
    id: str
    template_id: str
    cookie_profile_id: str | None = None
    status: str
    start_url: str
    created_at: datetime
    completed_at: datetime | None = None
    actions: list["RecordedActionRead"] = []

    model_config = {"from_attributes": True}


class RecordedActionRead(BaseModel):
    id: str
    recording_id: str
    sequence: int
    action_type: str
    user_description: str | None = None
    result_description: str | None = None
    action_context: dict | None = None
    page_url: str | None = None
    request_method: str | None = None
    request_url: str | None = None
    request_headers: dict | None = None
    request_body: dict | None = None
    response_status: int | None = None
    response_headers: dict | None = None
    response_body: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
