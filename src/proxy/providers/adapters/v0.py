"""
Adapter for v0.app (Vercel AI) with RSC streaming and multi-step session support.

v0 uses a custom React Server Components (RSC) streaming protocol, NOT standard SSE.
The response is a sequence of progressive JSON patches like:
  {"0":[[0,[["AssistantMessageContentPart",{"part":{...}}]]]],"1":[[1,{}]],"_t":"a"}

Text content is embedded in:
  ["p",{},["text",{},"actual response text"]]

Session lifecycle (multi-step):
  1. prepare_session() → POST /api/chat/project/blank → {chatId, blockId}
  2. build_payload()   → POST /chat/api/chat with message
  3. extract_meta()    → capture x-v0-response-message-id as parentId
  4. extract_content() → decode RSC → plain text
"""

import json
import re
import time
import uuid
from typing import Any

import httpx

from src.proxy.providers.base import BaseProviderAdapter
from src.proxy.providers.registry import register_adapter

# ── Team slug extraction from cookie domain ──────────────────────────

_TEAM_SLUG_RE = re.compile(r"/([^/]+?)(?:s-projects|/)")


def _extract_team_slug(cookies: dict[str, str] | None) -> str | None:
    """Try to extract team slug from v0 session cookies."""
    if not cookies:
        return None
    # v0 stores team info in various cookies; try _vercel_jwt or similar
    for key in ("_vercel_jwt", "v0_session", "v0_team"):
        val = cookies.get(key)
        if val:
            m = _TEAM_SLUG_RE.search(val)
            if m:
                return m.group(1)
    return None


# ── RSC Decoder ──────────────────────────────────────────────────────


class RSCDecoder:
    """
    Decodes v0's React Server Components streaming format.
    
    The format is a sequence of newline-delimited JSON patches.
    Each line is a JSON object. Text content lives in:
      ["p", {}, ["text", {}, "content here"]]
    
    This decoder extracts text from accumulated RSC state.
    """

    def __init__(self) -> None:
        self._state: dict[str, Any] = {}
        self._text_parts: list[str] = []
        self._last_extracted: str = ""  # весь текст, извлечённый в прошлый раз

    def feed(self, line: str) -> str | None:
        """
        Feed a raw line from the RSC stream.
        Returns newly extracted text since last feed, None if nothing new.
        """
        line = line.strip()
        if not line:
            return None
        try:
            chunk = json.loads(line)
        except json.JSONDecodeError:
            return None

        self._apply_patch(chunk)
        return self._extract_delta()

    def get_full_text(self) -> str:
        """Get all accumulated text so far."""
        # Final extraction — scan full state once
        all_text = self._scan_full_text()
        return all_text

    def _scan_full_text(self) -> str:
        """Scan the entire accumulated state for text content."""
        return self._join_texts(self._scan_for_text(self._state))

    @staticmethod
    def _join_texts(texts: list[str]) -> str:
        """Join text fragments, filtering out already-seen duplicates."""
        seen: set[str] = set()
        parts: list[str] = []
        for t in texts:
            clean = t.strip()
            if clean and clean not in seen:
                seen.add(clean)
                parts.append(clean)
        return " ".join(parts)

    # ── Internal ─────────────────────────────────────────────────

    def _apply_patch(self, chunk: dict[str, Any]) -> None:
        """
        Apply a progressive JSON patch to internal state.
        RSC patches use keys like "0", "1", "_t" for merge operations.
        """
        if not isinstance(chunk, dict):
            return

        # Simple merge into state
        for key, value in chunk.items():
            if key == "_t":
                continue  # internal type marker
            if isinstance(value, dict) and isinstance(self._state.get(key), dict):
                self._state[key].update(value)
            elif isinstance(value, list) and isinstance(self._state.get(key), list):
                self._state[key].extend(value)
            else:
                self._state[key] = value

    def _extract_delta(self) -> str | None:
        """
        Scan the accumulated state and return only NEW text
        since the last extraction (based on substring diff).
        """
        current = self._scan_full_text()
        if not current:
            return None

        # Find what's new since last extraction
        if current == self._last_extracted:
            return None

        if not self._last_extracted:
            self._last_extracted = current
            return current

        # If current starts with last, return the suffix as delta
        if current.startswith(self._last_extracted):
            delta = current[len(self._last_extracted):].strip()
            self._last_extracted = current
            return delta if delta else None

        # Otherwise return the full current as new
        self._last_extracted = current
        return current

    @staticmethod
    def _scan_for_text(data: Any, depth: int = 0) -> list[str]:
        """Recursively scan for ["p", {}, ["text", {}, "..."]] in data."""
        if depth > 20:
            return []
        results: list[str] = []
        matched_paragraph = False

        if isinstance(data, list):
            # Check if this is a paragraph with text: ["p", {}, ["text", {}, "content"]]
            if (
                len(data) >= 3
                and isinstance(data[0], str)
                and data[0] == "p"
                and isinstance(data[2], list)
            ):
                text_entry = data[2]
                if (
                    isinstance(text_entry, list)
                    and len(text_entry) >= 3
                    and isinstance(text_entry[0], str)
                    and text_entry[0] == "text"
                ):
                    text_val = text_entry[2] if len(text_entry) > 2 else ""
                    if isinstance(text_val, str) and text_val.strip():
                        results.append(text_val)
                        matched_paragraph = True  # skip recursion into children

            # Check for direct text arrays: ["text", {}, "content"]
            if not matched_paragraph and (
                len(data) >= 3
                and isinstance(data[0], str)
                and data[0] == "text"
            ):
                text_val = data[2] if len(data) > 2 else ""
                if isinstance(text_val, str) and text_val.strip():
                    results.append(text_val)

            # Recurse into nested lists (skip if paragraph was fully matched)
            if not matched_paragraph:
                for item in data:
                    results.extend(RSCDecoder._scan_for_text(item, depth + 1))

        elif isinstance(data, dict):
            for value in data.values():
                results.extend(RSCDecoder._scan_for_text(value, depth + 1))

        # Deduplicate while preserving order
        seen = set()
        return [x for x in results if not (x in seen or seen.add(x))]

    def decode_response(self, response_text: str) -> str:
        """
        Decode a full RSC response (non-streaming) into plain text.
        Each line is a JSON patch; we apply all, then extract final text once.
        """
        # Apply all patches without extracting text between them
        for line in response_text.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
                self._apply_patch(chunk)
            except json.JSONDecodeError:
                pass
        # Single extraction at the end
        return self._scan_full_text()


# ── Adapter ──────────────────────────────────────────────────────────


@register_adapter
class V0Adapter(BaseProviderAdapter):
    provider_id = "v0"
    provider_name = "V0 by Vercel"
    url_pattern = "v0.app"
    supports = {"chat"}

    # RSC decoder instance (per-adapter, cleared per session)
    _rsc_decoder: RSCDecoder | None = None

    # ── Session: prepare (create chat project) ───────────────────

    async def prepare_session(
        self,
        body: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Initialize a v0 chat session:
        1. Create a blank project → {chatId, blockId}
        2. Fetch latest chat to get parentId for first message
        3. Determine team slug
        4. Return session vars
        """
        messages = body.get("messages", [])
        first_msg = messages[0].get("content", "Chat") if messages else "Chat"
        chat_name = self._sanitize_chat_name(first_msg)[:50]

        auth_headers = headers or self._build_base_headers()
        print(f"  🔍 v0: prepare_session starting, chat_name={chat_name!r}")

        # ── Create project via v0 API using shared session ──────────
        async with httpx.AsyncClient(verify=True, timeout=10.0) as client:
            chat_id, block_id = await self._create_blank_project(
                chat_name, auth_headers, client
            )
            print(f"  ✅ v0: project created, chatId={chat_id!r}, blockId={block_id!r}")

            # ── Fetch latest chat messages to get parentId ──────────
            parent_id = await self._fetch_first_parent_id(chat_id, auth_headers, client)

            # ── Determine team slug ─────────────────────────────────
            team = await self._resolve_team_slug(auth_headers, client)
            print(f"  ✅ v0: team resolved, slug={team!r}")

        now_ms = int(time.time() * 1000)
        print(f"  🔍 v0: session prepared OK")
        return {
            "chat_id": chat_id,
            "block_id": block_id,
            "team": team,
            "chat_creation_time": now_ms,
            "message_id": uuid.uuid4().hex,
            "parent_id": parent_id,
            "last_user_message": "",
            "is_new_chat": False,
        }

    def _sanitize_chat_name(self, text: str) -> str:
        clean = re.sub(r"[^a-zA-Z0-9а-яА-Я\s\-_]", "", text)
        return clean.strip() or "Chat"

    async def _create_blank_project(
        self, chat_name: str, headers: dict[str, str], client: httpx.AsyncClient
    ) -> tuple[str, str]:
        """POST /api/chat/project/blank → {chatId, blockId}"""
        url = "https://v0.app/api/chat/project/blank"
        try:
            resp = await client.post(url, headers=headers, json={"chatName": chat_name})
            body = resp.text[:500]
            print(f"  🔍 v0: POST /api/chat/project/blank → {resp.status_code}")
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"Failed to create v0 project: {resp.status_code} {body}"
                )
            data = resp.json()
            chat_id = data.get("chatId", "")
            block_id = data.get("blockId", "")
            if not chat_id:
                raise RuntimeError(
                    f"v0 project creation returned empty chatId. Response: {body}"
                )
            return chat_id, block_id
        except httpx.RequestError as e:
            raise RuntimeError(f"v0 project creation failed: {e}") from e

    async def _fetch_first_parent_id(
        self, chat_id: str, headers: dict[str, str], client: httpx.AsyncClient
    ) -> str | None:
        """
        Fetch the latest chat messages to find the parentId for the first user message.
        After creating a blank project, v0 generates a system assistant message.
        We need its ID as parentId for our first user message.
        """
        url = f"https://v0.app/api/chat/chat/latest?chatId={chat_id}&lastSyncedAt=0"
        try:
            resp = await client.get(url, headers=headers)
            print(f"  🔍 v0: GET /api/chat/chat/latest → {resp.status_code}")
            if resp.status_code != 200:
                print(f"  ⚠️  v0: /api/chat/chat/latest returned {resp.status_code}")
                return None

            data = resp.json()
            if not data:
                print(f"  ⚠️  v0: /api/chat/chat/latest returned empty body")
                return None

            # v0 wraps in ok/value envelope
            value = data.get("value") if data.get("ok") else data
            if not value:
                return None

            new_messages = value.get("newMessages", []) if isinstance(value, dict) else []
            # Find the last assistant message to use as parent
            for msg in reversed(new_messages):
                if msg.get("role") == "assistant" and msg.get("id"):
                    pid = msg["id"]
                    print(f"  ✅ v0: found parentId={pid!r}")
                    return pid

            print(f"  ⚠️  v0: no assistant message found in latest chat")
            return None
        except (httpx.RequestError, json.JSONDecodeError) as e:
            print(f"  ⚠️  v0: failed to fetch parentId: {e}")
            return None

    # ── Known v0 model IDs (from recordings) ────────────────────────
    _V0_MODELS = [
        "v0-mini",
        "v0-pro",
        "v0-max",
        "v0-max-fast",
        "v0-gpt-5.6-sol",
        "v0-fable-5",
        # "v0-fable-3",  # seen in recordings but not used
    ]

    def get_model_id(self, provider_id: str) -> str:
        """Return default v0 model for proxy_request when model not specified."""
        return "v0-mini"

    def get_model_ids(self, provider_id: str) -> list[str]:
        """Return real v0 model IDs instead of generic provider_id/chat."""
        return list(self._V0_MODELS)

    # ── Team slug resolution ────────────────────────────────────────

    async def _resolve_team_slug(
        self, headers: dict[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> str:
        """
        Determine the team slug for API calls.
        Calls /api/auth/info to get user info and extracts the
        default team slug from the response.
        """
        url = "https://v0.app/api/auth/info"
        req_headers = headers or self._build_base_headers()

        async def _fetch(session: httpx.AsyncClient) -> str:
            try:
                resp = await session.get(url, headers=req_headers)
                if resp.status_code == 200:
                    info_data = resp.json()
                    if info_data is None:
                        print("  ⚠️  v0: /api/auth/info returned null body")
                        return "default-team"
                    user = info_data.get("user") or {}
                    # Try teamIdBySlug mapping first
                    slug_map = user.get("teamIdBySlug", {})
                    default_team_id = user.get("defaultTeamId", "")
                    for slug, tid in slug_map.items():
                        if tid == default_team_id:
                            print(f"  ✅ v0: team slug from teamIdBySlug: {slug!r}")
                            return slug
                    # Fallback: construct from username
                    username = user.get("username", "")
                    if username:
                        slug = f"{username}s-projects"
                        print(f"  ✅ v0: team slug from username: {slug!r}")
                        return slug
                    print("  ⚠️  v0: /api/auth/info missing username")
                else:
                    print(f"  ⚠️  v0: /api/auth/info returned {resp.status_code}")
            except httpx.RequestError as e:
                print(f"  ⚠️  v0: failed to resolve team slug: {e}")

            return "default-team"

        if client:
            return await _fetch(client)
        async with httpx.AsyncClient(verify=True, timeout=10.0) as session:
            return await _fetch(session)

    @staticmethod
    def _build_base_headers() -> dict[str, str]:
        """Build minimal headers for v0 API calls (no cookies)."""
        return {
            "Content-Type": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
            ),
        }

    # ── Session: extract meta from response ──────────────────────

    def extract_meta(
        self, response_headers: dict[str, str], response_body: Any
    ) -> dict[str, Any]:
        """
        Extract session metadata from response headers.
        v0 returns x-v0-response-message-id → used as parentId for next request.
        """
        meta: dict[str, Any] = {}

        # Capture response message ID for parent chaining
        parent_id = response_headers.get("x-v0-response-message-id")
        if parent_id:
            meta["parent_id"] = parent_id

        # Generate a new message ID for the next request
        meta["message_id"] = uuid.uuid4().hex
        meta["is_new_chat"] = False

        return meta

    # ── Payload building ─────────────────────────────────────────

    def build_payload(
        self,
        endpoint_key: str,
        body: dict[str, Any],
        block: str = "chat",
    ) -> dict[str, Any]:
        """
        Build the v0 chat request payload.
        Overrides default because v0 needs:
        - messageContent with mdx format
        - session context (chatId, parentId, etc.)
        - model configuration
        """
        messages = body.get("messages", [])
        last_msg = self._get_last_user_message(messages)

        # Update session with current message
        self.session["last_user_message"] = last_msg
        if "message_id" not in self.session or not self.session["message_id"]:
            self.session["message_id"] = uuid.uuid4().hex

        # Default model
        model_id = body.get("model", "v0-mini")

        payload = {
            "messageContent": {
                "version": 1,
                "parts": [{"type": "mdx", "content": last_msg}],
                "type": "parts",
            },
            "messageId": self.session.get("message_id", uuid.uuid4().hex),
            "chatId": self.session.get("chat_id", ""),
            "isNew": self.session.get("is_new_chat", True),
            "parentId": self.session.get("parent_id"),
            "team": self.session.get("team", "default-team"),
            "modelConfiguration": {
                "modelId": model_id,
                "imageGenerations": True,
                "thinking": False,
            },
            "optimisticConnectedIntegrations": [],
            "optimisticEnvVarKeys": [],
            "suggestedActionsEnabled": True,
            "mcpServers": [],
            "permissionsMode": "auto",
            "chatCreationTime": self.session.get(
                "chat_creation_time", int(time.time() * 1000)
            ),
            "previewViewport": {
                "mode": "desktop",
                "width": 960,
                "height": 583,
                "colorScheme": "light",
            },
        }

        print(f"  🔍 v0: build_payload → chatId={payload['chatId']!r}, "
              f"parentId={payload['parentId']!r}, isNew={payload['isNew']}, "
              f"modelId={payload['modelConfiguration']['modelId']!r}")
        return payload

    @staticmethod
    def _get_last_user_message(messages: list[dict[str, Any]]) -> str:
        """Extract the last user message from OpenAI messages array."""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    # Handle content arrays (multi-modal)
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            return part.get("text", "")
                    return ""
                return str(content)
        return ""

    # ── Response extraction (RSC) ─────────────────────────────────

    def extract_content(
        self,
        data: dict[str, Any] | str | list,
        block: str = "chat",
    ) -> str:
        """
        Extract text from v0's RSC response.
        Handles both the raw response text (string) and parsed JSON.
        """
        if isinstance(data, str):
            # Raw RSC response text
            decoder = RSCDecoder()
            return decoder.decode_response(data)

        if isinstance(data, dict):
            # Might be JSON with text content
            text = data.get("text") or data.get("content") or data.get("response")
            if text:
                return str(text)

            # Try OpenAI-compatible format
            choices = data.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                content = msg.get("content", "")
                if content:
                    return content

        return ""

    def extract_stream_chunk(
        self,
        chunk_data: dict[str, Any],
        block: str = "chat",
    ) -> str | None:
        """
        Extract text from a single RSC streaming chunk.
        v0 returns progressive JSON patches; we feed them to RSCDecoder.
        """
        # Initialize decoder if needed
        if self._rsc_decoder is None:
            self._rsc_decoder = RSCDecoder()

        # The chunk is already parsed JSON — serialize and feed as raw line
        raw_line = json.dumps(chunk_data, ensure_ascii=False)
        return self._rsc_decoder.feed(raw_line)
