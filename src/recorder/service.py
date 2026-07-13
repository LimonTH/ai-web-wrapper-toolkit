from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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

    adapter = get_registry().get_adapter_by_template(
        type("DummyTemplate", (), {
            "name": template_id_or_name,
            "base_url": "",
        })()
    )
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

    # Collect ALL API responses per action sequence (not just the first one)
    api_by_action_seq: dict[int, list[dict[str, Any]]] = {}
    for action in raw_actions:
        if action.get("type") == "api_response" and "linkedToAction" in action:
            linked_seq = action["linkedToAction"]
            api_by_action_seq.setdefault(linked_seq, []).append(action)

    saved_count = 0
    for i, action in enumerate(raw_actions):
        if action.get("type") == "api_response":
            continue

        action_ctx: dict[str, Any] = {
            "element": action.get("element"),
            "elementText": action.get("elementText"),
            "href": action.get("href"),
            "selector": action.get("selector"),
            "formData": action.get("formData"),
            "inputValue": action.get("inputValue"),
        }

        recorded = RecordedAction(
            recording_id=recording.id,
            sequence=i + 1,
            action_type=action.get("type", "unknown"),
            user_description=action.get("userDescription") or action.get("user_description"),
            result_description=action.get("resultDescription") or action.get("result_description"),
            action_context=action_ctx,
            page_url=action.get("pageUrl"),
        )
        db.add(recorded)
        saved_count += 1

        linked_apis = api_by_action_seq.get(action.get("seq"))
        if linked_apis:
            first = linked_apis[0]
            recorded.request_method = first.get("requestMethod")
            recorded.request_url = first.get("requestUrl")
            recorded.request_headers = first.get("requestHeaders")
            recorded.request_body = _try_parse_json(first.get("requestBody"))
            recorded.response_status = first.get("responseStatus")
            recorded.response_headers = first.get("responseHeaders")
            recorded.response_body = _try_parse_json(first.get("responseBody"))

            if len(linked_apis) > 1:
                extra = []
                for extra_api in linked_apis[1:]:
                    extra.append({
                        "requestMethod": extra_api.get("requestMethod"),
                        "requestUrl": extra_api.get("requestUrl"),
                        "requestHeaders": extra_api.get("requestHeaders"),
                        "requestBody": _try_parse_json(extra_api.get("requestBody")),
                        "responseStatus": extra_api.get("responseStatus"),
                        "responseHeaders": extra_api.get("responseHeaders"),
                        "responseBody": extra_api.get("responseBody"),
                    })
                if action_ctx is None:
                    action_ctx = {}
                action_ctx["api_responses"] = extra

    recording.status = "completed"
    recording.completed_at = datetime.now(timezone.utc)
    await db.flush()

    # Auto-export anonymized provider config to data/providers/{name}.yaml
    try:
        from src.providers.seed import export_provider_config
        export_provider_config(
            template_name=template.name,
            base_url=template.base_url,
            raw_actions=raw_actions,
        )
    except Exception as exc:
        print(f"  ⚠️  Provider config export failed: {exc}")

    print(f"💾 Saved {saved_count} actions → recording {recording.id}")

    return {
        "recording_id": recording.id,
        "template_id": template_id,
        "actions_count": saved_count,
        "status": "completed",
    }


def _try_parse_json(value: Any) -> Any:
    """Tries to parse a JSON string into a dict; returns string as-is if not valid JSON."""
    if isinstance(value, str):
        result = safe_json_parse(value, default=value, silent=True)
        return result
    return value


async def export_recording_json(recording: ActionRecording) -> str:
    """
    Export recording to JSON file in data/recording/.
    Returns the file path.
    """
    export_dir = Path("data/recording")
    export_dir.mkdir(parents=True, exist_ok=True)

    filename = f"recording_{recording.id}.json"
    filepath = export_dir / filename

    actions_data = []
    for action in recording.actions:
        actions_data.append({
            "sequence": action.sequence,
            "action_type": action.action_type,
            "user_description": action.user_description,
            "result_description": action.result_description,
            "action_context": action.action_context,
            "page_url": action.page_url,
            "request_method": action.request_method,
            "request_url": action.request_url,
            "request_headers": action.request_headers,
            "request_body": action.request_body,
            "response_status": action.response_status,
            "response_headers": action.response_headers,
            "response_body": action.response_body,
        })

    export_data = {
        "recording_id": recording.id,
        "template_id": recording.template_id,
        "status": recording.status,
        "start_url": recording.start_url,
        "created_at": recording.created_at.isoformat() if recording.created_at else None,
        "completed_at": recording.completed_at.isoformat() if recording.completed_at else None,
        "actions": actions_data,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)

    return str(filepath)


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