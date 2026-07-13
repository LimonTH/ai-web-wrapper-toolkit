"""
Provider seed config — portable YAML export from recorded actions.

Export: after recording, generates data/providers/{provider_id}.yaml (anonymized).
Import: YAML is read directly by ProviderConfig at runtime — no DB seeding needed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from src.core.config import settings
from src.proxy.providers.registry import get_registry

_PROVIDERS_DIR = Path(settings.project_root) / "data" / "providers"

# Headers to strip entirely (auth / personal)
_STRIP_HEADERS = frozenset({
    "cookie", "set-cookie",
    "authorization", "proxy-authorization",
    "x-is-human", "x-vercel-id", "x-vercel-proxy-signature",
    "user-agent",
    "x-forwarded-for", "x-real-ip",
    "cf-ray", "cf-connecting-ip",
})

# Body field patterns to anonymize (replace value with ${field_name})
_SENSITIVE_BODY_PATTERNS = re.compile(
    r"(project_id|user_id|session_id|team_id|author|nickname|username|email)"
    r"|team_\w+|project_[a-z0-9-]+",
    re.IGNORECASE,
)

# Path segment patterns that look like user-specific IDs
_PATH_ID_PATTERN = re.compile(
    r"/([a-z0-9]{20,}|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})"
    r"|/team_\w+"
    r"|/[a-z]+[0-9]{8,}",
    re.IGNORECASE,
)


def _ensure_dir() -> Path:
    _PROVIDERS_DIR.mkdir(parents=True, exist_ok=True)
    return _PROVIDERS_DIR


# ─── Anonymization helpers ────────────────────────────────────────


def _is_sensitive_key(key: str) -> bool:
    """Check if a dict key looks like it holds personal/account data."""
    low = key.lower()
    sensitive = {
        "cookie", "cookies", "authorization", "set-cookie",
        "user-agent", "x-is-human", "x-vercel-id",
        "session", "token", "jwt", "password", "secret",
        "email", "phone", "username",
    }
    return low in sensitive or any(s in low for s in ("token", "secret", "session", "auth"))


def _anonymize_headers(headers: dict[str, Any] | None) -> dict[str, Any] | None:
    """Strip auth/personal headers, keep only structural ones."""
    if not headers:
        return None
    safe = {}
    for k, v in headers.items():
        low = k.lower()
        if low in _STRIP_HEADERS or _is_sensitive_key(k):
            continue
        safe[k] = v
    return safe if safe else None


def _anonymize_url_path(path: str) -> str:
    """Replace user-specific path segments with placeholders."""
    def _replace_id(m: re.Match) -> str:
        segment = m.group(0)
        if "team_" in segment:
            return "/${team_id}"
        if "project_" in segment or len(segment.strip("/")) > 15:
            return "/${project_id}"
        return segment
    return _PATH_ID_PATTERN.sub(_replace_id, path)


def _anonymize_body(body: Any, path_hint: str = "") -> Any:
    """Recursively replace sensitive values with placeholders."""
    if isinstance(body, dict):
        cleaned = {}
        for k, v in body.items():
            low = k.lower()
            if _is_sensitive_key(k):
                continue
            if isinstance(v, str) and (
                re.match(r"^[a-f0-9]{8,}-", v)
                or re.match(r"^team_\w+$", v)
                or re.match(r"^[a-z]+[0-9]{8,}$", v)
                or len(v) > 30
            ):
                cleaned[k] = f"${{{k}}}"
            elif isinstance(v, (dict, list)):
                cleaned[k] = _anonymize_body(v, path_hint)
            else:
                cleaned[k] = v
        return cleaned
    if isinstance(body, list):
        return [_anonymize_body(item, path_hint) for item in body]
    return body


def _extract_unique_endpoints(raw_actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract unique API endpoint patterns from recorded actions."""
    seen: set[str] = set()
    endpoints: list[dict[str, Any]] = []

    for action in raw_actions:
        if action.get("type") != "api_response":
            continue

        url = action.get("requestUrl", "") or ""
        method = action.get("requestMethod", "GET") or "GET"
        body = action.get("requestBody")

        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path or url

        if "_rsc=" in url or "welcome-" in path or "greeting-" in path:
            continue

        safe_path = _anonymize_url_path(path)
        key = f"{method}:{safe_path}"
        if key in seen:
            continue
        seen.add(key)

        req_headers = _anonymize_headers(action.get("requestHeaders"))
        safe_body = None
        if body:
            try:
                parsed_body = json.loads(body) if isinstance(body, str) else body
                safe_body = _anonymize_body(parsed_body, safe_path)
            except (json.JSONDecodeError, TypeError):
                safe_body = None

        endpoints.append({
            "method": method,
            "path": safe_path,
            "headers_template": req_headers,
            "body_template": safe_body,
            "_original_url": url,
        })

    return endpoints


# ─── Export ────────────────────────────────────────────────────────


def export_provider_config(
    template_name: str,
    base_url: str,
    raw_actions: list[dict[str, Any]],
) -> Path | None:
    """
    Export anonymized provider config to data/providers/{name}.yaml.
    Uses the new YAML format (endpoints keyed by functional_block).

    Returns the file path, or None if no API endpoints were found.
    """
    ep_list = _extract_unique_endpoints(raw_actions)
    if not ep_list:
        return None

    # Build new-format YAML with endpoints grouped by block
    # Default all to "chat" block — user can refine manually
    endpoints_yaml = {}
    for i, ep in enumerate(ep_list):
        block = "chat"
        key = block if block not in endpoints_yaml else f"{block}_{i}"
        endpoints_yaml[key] = {
            "path": ep["path"],
            "method": ep["method"],
        }
        if ep.get("headers_template"):
            endpoints_yaml[key]["headers"] = ep["headers_template"]
        if ep.get("body_template"):
            endpoints_yaml[key]["body"] = ep["body_template"]

    export = {
        "provider_id": template_name,
        "name": template_name,
        "base_url": base_url.rstrip("/"),
        "endpoints": endpoints_yaml,
    }

    out_dir = _ensure_dir()
    file_path = out_dir / f"{template_name}.yaml"

    with open(file_path, "w", encoding="utf-8") as f:
        yaml.dump(export, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print(f"  📄 Exported provider config → {file_path}")
    return file_path
