import json
from typing import Any


def safe_json_parse(data: str, default: Any = None, silent: bool = True) -> Any:
    """Safe JSON parse. silent=True — no logging (for bulk parsing)."""
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        if not silent:
            print(f"⚠️ [json] JSONDecodeError (first 200 chars): {data[:200]}")
        return default