import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Boolean, DateTime, ForeignKey, JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class AppSetting(Base):
    """Runtime settings stored in the database (changeable via UI without server restart)."""
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class WebsiteTemplate(Base):
    __tablename__ = "website_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    icon_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    auth_type: Mapped[str] = mapped_column(String(32), default="cookie")  # cookie | token | basic | oauth | none
    capabilities: Mapped[list] = mapped_column(JSON, default=list)  # ["chat","projects","skills","image_gen","files","tools"]
    default_headers: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    endpoints: Mapped[list["ApiEndpoint"]] = relationship("ApiEndpoint", back_populates="template", cascade="all, delete-orphan")
    cookie_profiles: Mapped[list["CookieProfile"]] = relationship("CookieProfile", back_populates="template", cascade="all, delete-orphan")
    virtual_keys: Mapped[list["VirtualApiKey"]] = relationship("VirtualApiKey", back_populates="template", cascade="all, delete-orphan")


class ApiEndpoint(Base):
    __tablename__ = "api_endpoints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    template_id: Mapped[str] = mapped_column(ForeignKey("website_templates.id", ondelete="CASCADE"), nullable=False)

    functional_block: Mapped[str] = mapped_column(String(64), nullable=False)  # chat | projects | skills | image_gen | files | tools
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)  # GET, POST, PUT, DELETE
    path: Mapped[str] = mapped_column(String(512), nullable=False)

    headers_template: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    query_params_template: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    body_template: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    response_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    is_streaming: Mapped[bool] = mapped_column(Boolean, default=False)
    stream_event_field: Mapped[str | None] = mapped_column(String(64), nullable=True)

    order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    template: Mapped["WebsiteTemplate"] = relationship("WebsiteTemplate", back_populates="endpoints")


class CookieProfile(Base):
    __tablename__ = "cookie_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    template_id: Mapped[str] = mapped_column(ForeignKey("website_templates.id", ondelete="CASCADE"), nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    cookies: Mapped[list] = mapped_column(JSON, default=list)  # Playwright format (list[dict])
    extra_headers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    storage_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # localStorage, sessionStorage

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    template: Mapped["WebsiteTemplate"] = relationship("WebsiteTemplate", back_populates="cookie_profiles")


class VirtualApiKey(Base):
    __tablename__ = "virtual_api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    template_id: Mapped[str] = mapped_column(ForeignKey("website_templates.id", ondelete="CASCADE"), nullable=False)
    cookie_profile_id: Mapped[str | None] = mapped_column(ForeignKey("cookie_profiles.id", ondelete="SET NULL"), nullable=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_value: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)  # wsk_live_xxx
    key_prefix: Mapped[str] = mapped_column(String(16), default="wsk")
    jwt_token: Mapped[str | None] = mapped_column(Text, nullable=True)

    config_overrides: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    template: Mapped["WebsiteTemplate"] = relationship("WebsiteTemplate", back_populates="virtual_keys")
    cookie_profile: Mapped["CookieProfile | None"] = relationship("CookieProfile")


class ActionRecording(Base):
    """Session recording user actions."""
    __tablename__ = "action_recordings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    template_id: Mapped[str] = mapped_column(ForeignKey("website_templates.id", ondelete="CASCADE"), nullable=False)
    cookie_profile_id: Mapped[str | None] = mapped_column(ForeignKey("cookie_profiles.id", ondelete="SET NULL"), nullable=True)

    status: Mapped[str] = mapped_column(String(32), default="recording")  # recording | completed | cancelled
    start_url: Mapped[str] = mapped_column(String(512), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    template: Mapped["WebsiteTemplate"] = relationship("WebsiteTemplate")
    cookie_profile: Mapped["CookieProfile | None"] = relationship("CookieProfile")
    actions: Mapped[list["RecordedAction"]] = relationship(
        "RecordedAction", back_populates="recording",
        cascade="all, delete-orphan", order_by="RecordedAction.sequence"
    )


class RecordedAction(Base):
    """A single user action on the website."""
    __tablename__ = "recorded_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    recording_id: Mapped[str] = mapped_column(ForeignKey("action_recordings.id", ondelete="CASCADE"), nullable=False)

    sequence: Mapped[int] = mapped_column(Integer, default=0)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)  # click | input | submit | navigation | other
    user_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_context: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    page_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    request_method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    request_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    request_headers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    request_body: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_headers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    response_body: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    recording: Mapped["ActionRecording"] = relationship("ActionRecording", back_populates="actions")