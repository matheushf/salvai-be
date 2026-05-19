#!/usr/bin/env python3
"""Create Supabase Auth users and fill ``public.profiles`` for testing.

The ``on_auth_user_created`` trigger inserts a profile stub; this script sets
username, display_name, and bio (service role bypasses RLS).

Each user has ``user_metadata.salvai_fake_seed = true``. IDs are stored in a JSON
state file for ``delete_fake_users.py``.

Examples (from salvai-be/)::

    uv run python scripts/seed_fake_users.py
    uv run python scripts/seed_fake_users.py --count 5 --password 'YourLongPass!123'
    uv run python scripts/seed_fake_users.py --append

"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    from supabase_auth.errors import AuthApiError
except ImportError:
    AuthApiError = Exception  # type: ignore[misc, assignment]

from fake_users_lib import (
    DEFAULT_STATE_FILE,
    USER_METADATA_MARKER,
    get_service_client,
    load_state,
    load_settings_only,
    save_state,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--count", type=int, default=3, help="Number of users to create")
    p.add_argument(
        "--prefix",
        type=str,
        default="fake",
        help="Username prefix (letters/digits/underscore; final name is prefix_<uniq>)",
    )
    p.add_argument(
        "--password",
        type=str,
        default="SalvaiFakeSeed!change-me",
        help="Password for all seeded users (change for shared secrets)",
    )
    p.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_STATE_FILE,
        help=f"Where to store created user ids (default: {DEFAULT_STATE_FILE})",
    )
    p.add_argument(
        "--append",
        action="store_true",
        help="Merge with existing state file instead of replacing it",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    if args.count < 1:
        print("--count must be >= 1", file=sys.stderr)
        return 1
    if len(args.prefix) < 1:
        print("--prefix must be non-empty", file=sys.stderr)
        return 1

    load_settings_only()
    client, _settings = get_service_client()

    if not args.append and args.state_file.is_file():
        print(
            "Note: state file will be replaced with this batch only "
            "(use --append to keep prior IDs).",
            file=sys.stderr,
        )

    existing_by_id: dict[str, dict] = {}
    if args.append and args.state_file.is_file():
        for row in load_state(args.state_file):
            uid = row.get("id")
            if isinstance(uid, str):
                existing_by_id[uid] = row

    created: list[dict] = []
    run_tag = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    for i in range(args.count):
        uniq = uuid.uuid4().hex[:12]
        username = f"{args.prefix}_{uniq}"
        email = f"salvai-fake-{run_tag}-{i}-{uniq}@invalid.local"
        try:
            resp = client.auth.admin.create_user(
                {
                    "email": email,
                    "password": args.password,
                    "email_confirm": True,
                    "user_metadata": {
                        USER_METADATA_MARKER: True,
                        "seed_run": run_tag,
                        "index": i,
                    },
                }
            )
        except AuthApiError as e:
            print(f"Auth create_user failed for {email}: {e}", file=sys.stderr)
            return 1

        uid = resp.user.id
        display_name = f"Fake user {i + 1}"
        bio = f"Seeded by scripts/seed_fake_users.py ({run_tag})"

        upd = (
            client.table("profiles")
            .update(
                {
                    "username": username,
                    "display_name": display_name,
                    "bio": bio,
                }
            )
            .eq("id", uid)
            .execute()
        )
        if not upd.data:
            print(
                f"Warning: profile update returned no rows for {uid} — "
                "check migrations/trigger on auth.users",
                file=sys.stderr,
            )

        rec = {
            "id": uid,
            "email": email,
            "username": username,
            "seed_run": run_tag,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        created.append(rec)
        existing_by_id[uid] = rec
        print(f"Created user {uid}  email={email}  username={username}")

    out_list = list(existing_by_id.values())
    args.state_file.parent.mkdir(parents=True, exist_ok=True)
    save_state(args.state_file, out_list)
    print(f"\nWrote {len(created)} new record(s); state has {len(out_list)} total -> {args.state_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
