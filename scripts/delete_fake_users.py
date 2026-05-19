#!/usr/bin/env python3
"""Delete seeded fake users from Supabase Auth.

Deleting Auth users cascades to ``public.profiles``, then ``follows``, ``events``, etc.

User IDs are gathered from: the JSON state file from ``seed_fake_users.py``,
optional ``--from-metadata`` (scan Auth for ``user_metadata.salvai_fake_seed``),
and optional repeated ``--id``.

Examples (from salvai-be/)::

    uv run python scripts/delete_fake_users.py --dry-run
    uv run python scripts/delete_fake_users.py --yes --wipe-state-file
    uv run python scripts/delete_fake_users.py --yes --from-metadata
    uv run python scripts/delete_fake_users.py --yes --id <uuid>

"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from supabase_auth.errors import AuthApiError
except ImportError:
    AuthApiError = Exception  # type: ignore[misc, assignment]

from fake_users_lib import (
    DEFAULT_STATE_FILE,
    USER_METADATA_MARKER,
    get_service_client,
    load_settings_only,
    load_state,
    save_state,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--yes",
        action="store_true",
        help="Confirm deletion (required unless using --dry-run)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print users that would be deleted without calling the API",
    )
    p.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_STATE_FILE,
        help=f"State file from seed script (default: {DEFAULT_STATE_FILE})",
    )
    p.add_argument(
        "--from-metadata",
        action="store_true",
        help="Find users via user_metadata flag instead of (or in addition to) state file",
    )
    p.add_argument(
        "--id",
        dest="extra_ids",
        action="append",
        default=[],
        metavar="UUID",
        help="Extra Auth user id to delete (repeatable)",
    )
    p.add_argument(
        "--wipe-state-file",
        action="store_true",
        help="Rewrite the state file, keeping only users that failed to delete",
    )
    return p.parse_args()


def _collect_ids_from_state(path: Path) -> list[str]:
    ids: list[str] = []
    for row in load_state(path):
        uid = row.get("id")
        if isinstance(uid, str):
            ids.append(uid)
    return ids


def _collect_ids_from_metadata(client, max_pages: int = 50) -> list[str]:
    ids: list[str] = []
    for page in range(1, max_pages + 1):
        users = client.auth.admin.list_users(page=page, per_page=200)
        if not users:
            break
        for u in users:
            meta = u.user_metadata or {}
            if meta.get(USER_METADATA_MARKER) is True:
                ids.append(u.id)
        if len(users) < 200:
            break
    return ids


def main() -> int:
    args = _parse_args()
    if not args.dry_run and not args.yes:
        print("Refusing to delete without --yes (or use --dry-run).", file=sys.stderr)
        return 1

    load_settings_only()
    client, _settings = get_service_client()

    ids: list[str] = []
    ids.extend(args.extra_ids)
    ids.extend(_collect_ids_from_state(args.state_file))
    if args.from_metadata:
        ids.extend(_collect_ids_from_metadata(client))

    # de-dupe preserving order
    seen: set[str] = set()
    unique_ids: list[str] = []
    for uid in ids:
        if uid not in seen:
            seen.add(uid)
            unique_ids.append(uid)

    if not unique_ids:
        print("No user ids to delete.")
        return 0

    print(f"{'Would delete' if args.dry_run else 'Deleting'} {len(unique_ids)} user(s):")
    for uid in unique_ids:
        print(f"  - {uid}")

    if args.dry_run:
        return 0

    failed: list[str] = []
    for uid in unique_ids:
        try:
            client.auth.admin.delete_user(uid)
            print(f"Deleted {uid}")
        except AuthApiError as e:
            if getattr(e, "status", None) == 404:
                print(f"Already absent (404): {uid}")
                continue
            print(f"FAILED {uid}: {e}", file=sys.stderr)
            failed.append(uid)

    if args.wipe_state_file and args.state_file.is_file():
        remaining = [r for r in load_state(args.state_file) if r.get("id") in failed]
        save_state(args.state_file, remaining)
        print(f"State file updated -> {len(remaining)} record(s) left in {args.state_file}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
