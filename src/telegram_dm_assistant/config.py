"""Environment-only settings; fails closed for messaging."""

import os
from dataclasses import dataclass
from pathlib import Path


def _enabled(value: str) -> bool:
    if value.lower() not in {"true", "false"}:
        raise ValueError("DM_SEND_ENABLED must be true or false")
    return value.lower() == "true"


@dataclass(frozen=True)
class Config:
    api_id: int
    api_hash: str
    allowed_user_ids: frozenset[int]
    send_enabled: bool
    llm_backend: str
    llm_api_key: str
    llm_model: str
    llm_base_url: str
    data_dir: Path
    allow_all: bool = False

    @classmethod
    def from_env(cls) -> "Config":
        raw_ids = os.getenv("DM_ALLOWED_USER_IDS", "")
        try:
            allowed = frozenset(int(value.strip()) for value in raw_ids.split(",") if value.strip())
            if any(value <= 0 for value in allowed):
                raise ValueError("allowlist IDs must be positive")
        except ValueError as exc:
            raise ValueError("DM_ALLOWED_USER_IDS must be comma-separated positive numeric IDs") from exc
        send = _enabled(os.getenv("DM_SEND_ENABLED", "false"))
        allow_all = _enabled(os.getenv("DM_ALLOW_ALL", "false"))
        if send and not (allowed or allow_all):
            raise ValueError("Cannot enable sending without an allowlist or DM_ALLOW_ALL=true")
        backend = os.getenv("LLM_BACKEND", "openrouter").lower()
        if backend not in {"openrouter", "openai"}:
            raise ValueError("LLM_BACKEND must be openrouter or openai")
        default_url = (
            "https://openrouter.ai/api/v1" if backend == "openrouter" else "https://api.openai.com/v1"
        )
        url = os.getenv("LLM_BASE_URL", default_url).rstrip("/")
        if not url.startswith("https://"):
            raise ValueError("LLM_BASE_URL must use HTTPS")
        key = os.getenv("LLM_API_KEY", "")
        model = os.getenv("LLM_MODEL", "")
        if not key or not model:
            raise ValueError("LLM_API_KEY and LLM_MODEL are required")
        api_id = int(os.environ["TG_API_ID"])
        api_hash = os.environ["TG_API_HASH"]
        if api_id <= 0 or not api_hash:
            raise ValueError("TG_API_ID and TG_API_HASH must be valid")
        return cls(
            api_id, api_hash, allowed, send, backend, key, model, url,
            Path(os.getenv("DM_DATA_DIR", "data")).resolve(), allow_all,
        )
