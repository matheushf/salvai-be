from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from urllib.parse import unquote, urlparse, urlunparse

from app.core.config import get_settings
from app.schemas.instagram import PostMetadataResponse

logger = logging.getLogger(__name__)

_TABLE = "enrich_cache"
_SHORTCODE_RE = re.compile(r"instagram\.com/(?:p|reel)/([A-Za-z0-9_-]+)")
_IG_DOMAINS = {"instagram.com", "www.instagram.com", "m.instagram.com"}
_BUSY_TIMEOUT_MS = 5000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS enrich_cache (
  url_key   TEXT PRIMARY KEY,
  url       TEXT NOT NULL,
  payload   TEXT NOT NULL,
  cached_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_initialized_paths: set[str] = set()


def normalize_enrich_url(url: str) -> str:
    """Return a stable cache key for an enrich URL."""
    decoded = unquote(url.strip())

    match = _SHORTCODE_RE.search(decoded)
    if match:
        parsed = urlparse(decoded)
        host = parsed.hostname
        if host is not None and host.lower() in _IG_DOMAINS:
            return f"instagram:{match.group(1)}"

    parsed = urlparse(decoded)
    host = parsed.hostname
    if host is None:
        return decoded.rstrip("/")

    host_lower = host.lower()
    port = parsed.port
    if port and not (
        (parsed.scheme == "https" and port == 443)
        or (parsed.scheme == "http" and port == 80)
    ):
        netloc = f"{host_lower}:{port}"
    else:
        netloc = host_lower

    path = parsed.path.rstrip("/")
    return urlunparse((parsed.scheme.lower(), netloc, path, "", parsed.query, ""))


def _get_connection(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=_BUSY_TIMEOUT_MS / 1000)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def _init_db(db_path: str) -> None:
    if db_path in _initialized_paths:
        return
    with _get_connection(db_path) as conn:
        _ensure_schema(conn)
    _initialized_paths.add(db_path)


def get_cached_enrich(url: str) -> PostMetadataResponse | None:
    settings = get_settings()
    if not settings.enrich_cache_enabled:
        return None

    url_key = normalize_enrich_url(url)
    db_path = settings.enrich_cache_db_path
    try:
        _init_db(db_path)
        with _get_connection(db_path) as conn:
            row = conn.execute(
                f"SELECT payload FROM {_TABLE} WHERE url_key = ?",
                (url_key,),
            ).fetchone()
            if row is None:
                return None
            data = json.loads(row[0])
            return PostMetadataResponse(**data)
    except Exception:
        logger.exception("enrich_cache read failed url_key=%s", url_key)
        return None


def set_cached_enrich(url: str, response: PostMetadataResponse) -> None:
    settings = get_settings()
    if not settings.enrich_cache_enabled:
        return

    url_key = normalize_enrich_url(url)
    db_path = settings.enrich_cache_db_path
    payload = response.model_dump_json()
    try:
        _init_db(db_path)
        with _get_connection(db_path) as conn:
            conn.execute(
                f"""
                INSERT INTO {_TABLE} (url_key, url, payload, cached_at)
                VALUES (?, ?, ?, datetime('now'))
                ON CONFLICT(url_key) DO UPDATE SET
                  url = excluded.url,
                  payload = excluded.payload,
                  cached_at = excluded.cached_at
                """,
                (url_key, url, payload),
            )
            conn.commit()
    except Exception:
        logger.exception("enrich_cache write failed url_key=%s", url_key)
