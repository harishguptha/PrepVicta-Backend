"""
Check Supabase Storage for duplicate images (same filename/hash under different
chapter folders) and optionally delete the extras.

Safe to run multiple times — dry-run by default.

Run:
    python check_supabase_dupes.py            # dry run — just report
    python check_supabase_dupes.py --delete   # actually remove extras
"""

import argparse
import os
from collections import defaultdict

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL         = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
BUCKET               = os.getenv("SUPABASE_STORAGE_BUCKET", "topic-images")


def list_all_files(sb) -> list[str]:
    """Return every object path in the bucket (handles pagination)."""
    paths = []
    offset = 0
    limit = 1000
    while True:
        items = sb.storage.from_(BUCKET).list(
            path="",
            options={"limit": limit, "offset": offset},
        )
        if not items:
            break
        # Items at root level are chapter folders
        for folder_item in items:
            folder_name = folder_item["name"]
            # List files inside each chapter folder
            inner = sb.storage.from_(BUCKET).list(
                path=folder_name,
                options={"limit": 10000, "offset": 0},
            )
            for f in (inner or []):
                paths.append(f"{folder_name}/{f['name']}")
        if len(items) < limit:
            break
        offset += limit
    return paths


def find_duplicates(paths: list[str]) -> dict[str, list[str]]:
    """Group paths by filename. Returns only filenames with more than one path."""
    by_name: dict[str, list[str]] = defaultdict(list)
    for p in paths:
        filename = p.rsplit("/", 1)[-1]  # hash.jpg
        by_name[filename].append(p)
    return {name: sorted(ps) for name, ps in by_name.items() if len(ps) > 1}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete duplicate files (keeps the first path, removes the rest).",
    )
    args = parser.parse_args()

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise SystemExit("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in .env")

    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    print(f"Listing files in bucket '{BUCKET}'…")
    all_paths = list_all_files(sb)
    print(f"Total files: {len(all_paths)}")

    dupes = find_duplicates(all_paths)

    if not dupes:
        print("No duplicate images found. Bucket is clean.")
        return

    total_extra = sum(len(ps) - 1 for ps in dupes.values())
    print(f"\nDuplicate filenames: {len(dupes)}  |  Extra copies to remove: {total_extra}")
    print("-" * 60)

    to_delete: list[str] = []
    for filename, paths in sorted(dupes.items()):
        keep = paths[0]
        extras = paths[1:]
        print(f"  {filename}")
        print(f"    KEEP  : {keep}")
        for ex in extras:
            print(f"    DELETE: {ex}")
            to_delete.append(ex)

    print("-" * 60)

    if not args.delete:
        print(f"\nDry run — {total_extra} extra file(s) would be removed.")
        print("Re-run with --delete to actually remove them.")
        return

    print(f"\nDeleting {len(to_delete)} duplicate file(s)…")
    removed = 0
    failed = 0
    for path in to_delete:
        try:
            sb.storage.from_(BUCKET).remove([path])
            print(f"  [DEL OK ] {path}")
            removed += 1
        except Exception as e:
            print(f"  [DEL FAIL] {path} — {e}")
            failed += 1

    print(f"\nDone. Removed: {removed}  Failed: {failed}")


if __name__ == "__main__":
    main()
