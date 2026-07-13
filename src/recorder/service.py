from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.config import settings
from src.core.exceptions import safe_json_parse
from src.core.models import ActionRecording, CookieProfile, RecordedAction, WebsiteTemplate
from src.recorder.recorder import record_actions

"""
Service layer for Action Recorder.
"""


async def _resolve_template(db: AsyncSession, template_id_or_name: str) -> WebsiteTemplate:
    """Finds a WebsiteTemplate by UUID or name (provider_id). Creates one if not found."""
    result = await db.execute(
        select(WebsiteTemplate).where(
            (WebsiteTemplate.id == template_id_or_name)
            | (WebsiteTemplate.name == template_id_or_name)
        )
    )
    template = result.scalar_one_or_none()
    if template:
        return template

    from src.proxy.providers.registry import get_registry

    dummy = type("DummyTemplate", (), {"name": template_id_or_name, "base_url": "", "endpoints": []})()
    adapter = get_registry().get_adapter(dummy)
    capabilities = sorted(adapter.supports) if adapter.supports else []
    url_pattern = getattr(adapter, "url_pattern", "") or ""
    base_url = f"https://{url_pattern}" if url_pattern else ""
    provider_name = getattr(adapter, "provider_name", template_id_or_name)

    template = WebsiteTemplate(
        name=template_id_or_name,
        base_url=base_url,
        description=provider_name,
        capabilities=capabilities,
    )
    db.add(template)
    await db.flush()
    return template


async def start_recording(
        db: AsyncSession,
        template_id: str,
        cookie_profile_id: str | None = None,
        headless: bool = False,
        with_prompts: bool = True,
) -> dict[str, Any]:
    """
    Start a recording session: open browser, capture actions, save to DB.
    """
    template = await _resolve_template(db, template_id)

    cookies = None
    storage_state = None
    if cookie_profile_id:
        cp_result = await db.execute(
            select(CookieProfile).where(CookieProfile.id == cookie_profile_id)
        )
        profile = cp_result.scalar_one_or_none()
        if profile:
            cookies = profile.cookies
            storage_state = profile.storage_state

    recording = ActionRecording(
        template_id=template_id,
        cookie_profile_id=cookie_profile_id,
        status="recording",
        start_url=template.base_url,
    )
    db.add(recording)
    await db.flush()

    print(f"\n🎬 Starting action recording for template: {template.name}")
    raw_actions = await record_actions(
        url=template.base_url,
        cookies=cookies,
        storage_state=storage_state,
        headless=headless,
        with_prompts=with_prompts,
    )

    api_by_action_seq: dict[int, dict[str, Any]] = {}
    for action in raw_actions:
        if action.get("type") == "api_response" and "linkedToAction" in action:
            linked_seq = action["linkedToAction"]
            if linked_seq not in api_by_action_seq:
                api_by_action_seq[linked_seq] = action

    saved_count = 0
    for i, action in enumerate(raw_actions):
        if action.get("type") == "api_response":
            continue

        recorded = RecordedAction(
            recording_id=recording.id,
            sequence=i + 1,
            action_type=action.get("type", "unknown"),
            user_description=action.get("userDescription") or action.get("user_description"),
            result_description=action.get("resultDescription") or action.get("result_description"),
            action_context={
                "element": action.get("element"),
                "elementText": action.get("elementText"),
                "href": action.get("href"),
                "selector": action.get("selector"),
                "formData": action.get("formData"),
                "inputValue": action.get("inputValue"),
            },
            page_url=action.get("pageUrl"),
        )
        db.add(recorded)
        saved_count += 1

        linked_api = api_by_action_seq.get(action.get("seq"))
        if linked_api:
            recorded.request_method = linked_api.get("requestMethod")
            recorded.request_url = linked_api.get("requestUrl")
            recorded.request_headers = linked_api.get("requestHeaders")
            recorded.request_body = _try_parse_json(linked_api.get("requestBody"))
            recorded.response_status = linked_api.get("responseStatus")
            recorded.response_headers = linked_api.get("responseHeaders")
            recorded.response_body = _try_parse_json(linked_api.get("responseBody"))

    recording.status = "completed"
    recording.completed_at = datetime.now(timezone.utc)
    await db.flush()

    export_path = _export_recording(recording, raw_actions, template.name)

    print(f"💾 Saved {saved_count} actions → recording {recording.id}")
    print(f"📄 Exported to {export_path}")

    return {
        "recording_id": recording.id,
        "template_id": template_id,
        "actions_count": saved_count,
        "status": "completed",
        "export_path": str(export_path),
    }


def _try_parse_json(value: Any) -> Any:
    """Tries to parse a JSON string into a dict; returns string as-is if not valid JSON."""
    if isinstance(value, str):
        result = safe_json_parse(value, default=value, silent=True)
        return result
    return value


def _export_recording(
        recording: ActionRecording,
        raw_actions: list[dict[str, Any]],
        template_name: str,
) -> Path:
    """Exports recording to a JSON file for manual analysis."""
    recordings_dir = Path(settings.project_root) / "data" / "recordings"
    recordings_dir.mkdir(parents=True, exist_ok=True)

    export = {
        "recording_id": recording.id,
        "template": template_name,
        "start_url": recording.start_url,
        "created_at": recording.created_at.isoformat(),
        "completed_at": recording.completed_at.isoformat() if recording.completed_at else None,
        "actions_count": len(raw_actions),
        "actions": raw_actions,
    }

    file_path = recordings_dir / f"{recording.id}.json"
    file_path.write_text(json.dumps(export, indent=2, default=str, ensure_ascii=False))
    return file_path


async def get_recording(db: AsyncSession, recording_id: str) -> ActionRecording:
    """Get a recording session with all its actions."""
    result = await db.execute(
        select(ActionRecording)
        .options(selectinload(ActionRecording.actions))
        .where(ActionRecording.id == recording_id)
    )
    recording = result.scalar_one_or_none()
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")
    return recording


async def get_recordings_by_template(db: AsyncSession, template_id: str) -> list[ActionRecording]:
    """All recording sessions for a template, newest first."""
    result = await db.execute(
        select(ActionRecording)
        .where(ActionRecording.template_id == template_id)
        .order_by(ActionRecording.created_at.desc())
    )
    return list(result.scalars().all())
