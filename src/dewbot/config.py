from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_path(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _content_paths(raw: str | None) -> tuple[Path, ...]:
    if not raw:
        return (
            _resolve_path("content/base_pack.json"),
            _resolve_path("content/core_personas.json"),
        )
    # Use the platform path separator so Windows drive letters are never split.
    return tuple(
        _resolve_path(item.strip()) for item in raw.split(os.pathsep) if item.strip()
    )


def _admin_ids(raw: str | None) -> frozenset[int]:
    if not raw:
        return frozenset()
    try:
        values = frozenset(int(item.strip()) for item in raw.split(",") if item.strip())
    except ValueError as exc:
        raise ValueError("DEWBOT_ADMIN_IDS 必须是以逗号分隔的 Telegram 数字用户 ID") from exc
    if any(item <= 0 for item in values):
        raise ValueError("DEWBOT_ADMIN_IDS 中的 Telegram 用户 ID 必须大于 0")
    return values


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path
    content_paths: tuple[Path, ...]
    telegram_token: str | None
    telegram_proxy: str | None
    admin_ids: frozenset[int]
    web_host: str = "127.0.0.1"
    web_port: int = 8787
    web_gm_key: str | None = None
    web_player_key: str | None = None
    web_secure_cookie: bool = False
    story_enabled: bool = False
    story_database_path: Path | None = None
    ai_api_base: str | None = None
    ai_api_key: str | None = None
    ai_model: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(PROJECT_ROOT / ".env")
        return cls(
            database_path=_resolve_path(
                os.getenv("DEWBOT_DB_PATH", "src/data/dewbot_v2.db")
            ),
            content_paths=_content_paths(os.getenv("DEWBOT_CONTENT_PATHS")),
            telegram_token=(
                os.getenv("TELEGRAM_TOKEN")
                or os.getenv("TELEGRAM_BOT_TOKEN")
                or os.getenv("BOT_TOKEN")
            ),
            telegram_proxy=os.getenv("TELEGRAM_PROXY") or None,
            admin_ids=_admin_ids(os.getenv("DEWBOT_ADMIN_IDS")),
            web_host=os.getenv("DEWBOT_WEB_HOST", "127.0.0.1"),
            web_port=int(os.getenv("DEWBOT_WEB_PORT", "8787")),
            web_gm_key=os.getenv("DEWBOT_WEB_GM_KEY") or None,
            web_player_key=os.getenv("DEWBOT_WEB_PLAYER_KEY") or None,
            web_secure_cookie=(
                os.getenv("DEWBOT_WEB_SECURE_COOKIE", "").strip().lower()
                in {"1", "true", "yes", "on"}
            ),
            story_enabled=(
                os.getenv("DEWBOT_STORY_ENABLED", "").strip().lower()
                in {"1", "true", "yes", "on"}
            ),
            story_database_path=(
                _resolve_path(os.environ["DEWBOT_STORY_DB_PATH"])
                if os.getenv("DEWBOT_STORY_DB_PATH") else None
            ),
            ai_api_base=os.getenv("DEWBOT_AI_API_BASE") or None,
            ai_api_key=os.getenv("DEWBOT_AI_API_KEY") or None,
            ai_model=os.getenv("DEWBOT_AI_MODEL") or None,
        )
