"""Shared helpers for Supabase fake-user seed / cleanup scripts.

Requires ``salvai-be/.env`` with ``SUPABASE_URL`` and ``SUPABASE_SERVICE_ROLE_KEY``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from supabase import Client, create_client

_REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_STATE_FILE = _REPO_ROOT / ".salvai-fake-users.state.json"

USER_METADATA_MARKER = "salvai_fake_seed"


def add_repo_root_to_path() -> None:
    root = str(_REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def get_service_client() -> tuple[Client, Any]:
    """Return Supabase client with service role and Settings instance."""
    add_repo_root_to_path()
    from app.core.config import get_settings

    settings = get_settings()
    client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    return client, settings


def load_settings_only() -> Any:
    add_repo_root_to_path()
    from app.core.config import get_settings

    try:
        return get_settings()
    except ValidationError as e:
        print("Invalid or missing env (see salvai-be/.env.example):", file=sys.stderr)
        print(e, file=sys.stderr)
        raise SystemExit(1) from e


def load_state(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("State file must contain a JSON array")
    return data


def save_state(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
