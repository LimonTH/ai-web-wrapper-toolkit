# Adding New Web AI Providers

Guide for developers on how to add support for new AI websites.

## Overview

The toolkit has a plugin-based adapter system. Each AI website needs a **Python adapter class** in [`src/proxy/providers/adapters/`](src/proxy/providers/adapters/).

The registry auto-discovers adapters on server start — no manual registration needed.

## Quick Path

1. **Write the adapter** (Python class with `@register_adapter`)
2. **Restart the server** — adapter appears in the UI
3. **Record the site's API** via Recorder (discovers endpoints automatically)
4. **Test** via `/v1/{provider_id}/chat/completions`

## Steps

### 1. Write the adapter

Create a `.py` file in [`src/proxy/providers/adapters/`](src/proxy/providers/adapters/).

```python
from typing import Any
from src.core.models import ApiEndpoint, WebsiteTemplate
from src.proxy.providers.base import BaseProviderAdapter
from src.proxy.providers.registry import register_adapter


@register_adapter
class MySiteAdapter(BaseProviderAdapter):
    provider_id = "mysite"          # unique slug, used for routing
    provider_name = "My AI Site"    # display name in UI
    url_pattern = "mysite.com"      # auto-mapping via URL substring
    supports = {"chat"}             # functional blocks: chat, image_gen, files, tts, stt, tools

    def get_endpoint(
            self,
            template: WebsiteTemplate,
            block: str = "chat",
            method: str = "POST",
    ) -> ApiEndpoint | None:
        for ep in template.endpoints:
            if "chat/completions" in ep.path or "generate" in ep.path:
                return ep
        return None

    def build_payload(
            self,
            endpoint: ApiEndpoint,
            body: dict[str, Any],
            block: str = "chat",
    ) -> dict[str, Any]:
        # body is standard OpenAI chat completion request
        return {
            "messages": body.get("messages", []),
            "model": body.get("model", "default"),
            "stream": body.get("stream", False),
        }

    def extract_content(
            self,
            data: dict[str, Any] | str | list,
            block: str = "chat",
    ) -> str:
        if isinstance(data, dict):
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return data.get("content", "")
        if isinstance(data, str):
            return data
        return ""

    def extract_stream_chunk(
            self,
            chunk_data: dict[str, Any],
            block: str = "chat",
    ) -> str | None:
        choices = chunk_data.get("choices", [])
        if choices:
            delta = choices[0].get("delta", {})
            return delta.get("content")
        return None
```

### 2. Record the site's API

1. Restart the server — your adapter appears in the UI
2. Go to **Recorder** tab
3. Select your provider from the dropdown
4. Select a cookie profile (create one via **Cookies** → **Browser Login**)
5. Click **Start Recording**
6. Perform actions on the site, close the browser when done

The recorder automatically creates the provider record with discovered endpoints.

### 3. Understanding `supports` blocks

| Block | Description | OpenAI equivalent |
|-------|-------------|-------------------|
| `chat` | Text chat / conversation | `/chat/completions` |
| `image_gen` | Image generation | `/images/generations` |
| `files` | File upload / attachment support | — |
| `tools` | Function/tool calling | function calling |
| `tts` | Text-to-speech | `/audio/speech` |
| `stt` | Speech-to-text | `/audio/transcriptions` |

Each block must be implemented in `build_payload`, `extract_content`, `extract_stream_chunk`.

### 4. Auto-discovery

Adapters are auto-discovered on every server start:

- Any `.py` file in [`src/proxy/providers/adapters/`](src/proxy/providers/adapters/) (including subdirectories)
- Must inherit from `BaseProviderAdapter`
- Must define `provider_id`
- Must be decorated with `@register_adapter`

### 5. Testing

```bash
uv run python -m src.main

# Direct provider endpoint (bypasses key auth)
curl http://localhost:8000/v1/mysite/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello"}],"stream":false}'
```

## Existing Adapters

- [`deepseek.py`](src/proxy/providers/adapters/deepseek.py) — OpenAI-compatible API
- [`v0.py`](src/proxy/providers/adapters/v0.py) — custom format with RSC (React Server Components)
