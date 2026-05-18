"""
Ingestion script — reads both Biology zip files and:
  1. Uploads every image → Supabase Storage (bucket: topic-images)
  2. Rewrites image paths in MD → full Supabase public URLs
  3. Splits each chapter MD by ## headings into sections
  4. Upserts sections → Pinecone 'prepvictes' (auto-embedded by llama-text-embed-v2)

Run:
    python ingest_topics.py
"""

import re
import zipfile
from dotenv import load_dotenv
import os

from pinecone import Pinecone
from supabase import create_client, Client

load_dotenv()

# ── config ────────────────────────────────────────────────────────────────────
PINECONE_API_KEY     = os.getenv("pinecone_api_key", "")
SUPABASE_URL         = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

INDEX_NAME = os.getenv("PINECONE_INDEX", "")
NAMESPACE  = os.getenv("PINECONE_NAMESPACE", "")
BUCKET     = os.getenv("SUPABASE_STORAGE_BUCKET", "topic-images")
BATCH_SIZE   = 30

ZIP_CLASS12 = r"C:\Users\SanthoshKumarP\Downloads\output (10).zip"
ZIP_CLASS11 = r"C:\Users\SanthoshKumarP\Downloads\output (11).zip"


# ── Supabase Storage ──────────────────────────────────────────────────────────

def get_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def ensure_bucket(sb: Client):
    """Create the bucket if it doesn't exist, make it public."""
    try:
        sb.storage.create_bucket(BUCKET, options={"public": True})
        print(f"  Created bucket '{BUCKET}'")
    except Exception as e:
        if "already exists" in str(e).lower() or "Duplicate" in str(e):
            pass  # already exists, fine
        else:
            raise


_upload_ok = 0
_upload_fail = 0

def upload_image(sb: Client, img_bytes: bytes, storage_path: str) -> str:
    """Upload image bytes to Supabase Storage. Returns the public URL."""
    global _upload_ok, _upload_fail
    try:
        sb.storage.from_(BUCKET).upload(
            path=storage_path,
            file=img_bytes,
            file_options={"content-type": "image/jpeg", "upsert": "true"},
        )
        _upload_ok += 1
        print(f"    [IMG OK ] {storage_path} ({len(img_bytes):,} bytes)")
    except Exception as e:
        if "already exists" in str(e).lower() or "Duplicate" in str(e):
            _upload_ok += 1
            print(f"    [IMG SKIP] {storage_path} (already exists)")
        else:
            _upload_fail += 1
            print(f"    [IMG FAIL] {storage_path} — {e}")

    return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{storage_path}"


# ── MD processing ─────────────────────────────────────────────────────────────

def chapter_name_from_folder(folder: str) -> str:
    """'Ch05_Molecular_Basis_of_Inheritance' → 'Molecular Basis of Inheritance'"""
    parts = folder.split("_", 1)
    return parts[1].replace("_", " ") if len(parts) > 1 else folder


def split_md_into_sections(md_text: str) -> list[dict]:
    """
    Split chapter MD into sections at every ## heading.
    Returns list of {heading, content}.
    """
    lines = md_text.splitlines()
    sections = []
    current_heading = "Introduction"
    current_lines: list[str] = []

    for line in lines:
        if line.startswith("## "):
            if current_lines:
                sections.append({
                    "heading": current_heading,
                    "content": "\n".join(current_lines).strip(),
                })
            current_heading = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections.append({
            "heading": current_heading,
            "content": "\n".join(current_lines).strip(),
        })

    return [s for s in sections if len(s["content"]) > 80]


def make_record_id(class_label: str, folder: str, section_index: int) -> str:
    safe = re.sub(r"[^a-z0-9]", "-", folder.lower())
    label = class_label.replace(" ", "")
    return f"{label}-{safe}-s{section_index}"


# ── per-zip processing ────────────────────────────────────────────────────────

def process_zip(zip_path: str, class_label: str, sb: Client) -> list[dict]:
    """
    For each chapter in the zip:
      - Upload images to Supabase Storage
      - Rewrite image paths in MD to full Supabase URLs
      - Split MD into sections
    Returns list of Pinecone records.
    """
    records = []

    with zipfile.ZipFile(zip_path, "r") as zf:
        all_entries = zf.namelist()

        # Group by chapter folder
        chapter_folders = sorted({
            e.split("/")[0]
            for e in all_entries
            if "/" in e and e.split("/")[0].startswith("Ch")
        })

        for folder in chapter_folders:
            chapter = chapter_name_from_folder(folder)
            print(f"  Processing: {chapter}")

            # 1. Find and upload all images for this chapter
            image_url_map: dict[str, str] = {}   # "images/hash.jpg" → supabase URL
            image_entries = [
                e for e in all_entries
                if e.startswith(f"{folder}/") and "/images/" in e and e.endswith(".jpg")
            ]
            for img_entry in image_entries:
                filename = img_entry.split("/")[-1]          # hash.jpg
                storage_path = f"{folder}/{filename}"        # Ch05_Molecular.../hash.jpg
                img_bytes = zf.read(img_entry)
                public_url = upload_image(sb, img_bytes, storage_path)
                image_url_map[f"images/{filename}"] = public_url  # map relative → absolute

            # 2. Read and rewrite the MD file
            md_entries = [
                e for e in all_entries
                if e.startswith(f"{folder}/auto/") and e.endswith(".md")
            ]
            if not md_entries:
                continue

            raw_md = zf.read(md_entries[0]).decode("utf-8", errors="replace")

            # Replace every ![](images/hash.jpg) with the Supabase URL
            def replace_img(m: re.Match) -> str:
                rel_path = m.group(1)
                return f"![]({image_url_map.get(rel_path, rel_path)})"

            updated_md = re.sub(r"!\[\]\((images/[^)]+)\)", replace_img, raw_md)

            # 3. Split into sections and build Pinecone records
            sections = split_md_into_sections(updated_md)
            for idx, sec in enumerate(sections):
                # Extract image URLs that appear in this section
                section_images = re.findall(
                    r"!\[\]\((https://[^)]+)\)", sec["content"]
                )
                record = {
                    "_id":          make_record_id(class_label, folder, idx),
                    "text":         f"{chapter}\n{sec['heading']}\n\n{sec['content']}",
                    "subject":      "Biology",
                    "chapter":      chapter,
                    "section":      sec["heading"],
                    "class":        class_label,
                    "image_count":  len(section_images),
                    # store up to 5 image URLs as separate fields (Pinecone metadata)
                    **{f"img_{i}": url for i, url in enumerate(section_images[:5])},
                }
                records.append(record)

    return records


# ── upsert ────────────────────────────────────────────────────────────────────

def upsert_in_batches(index, namespace: str, records: list[dict]):
    total = len(records)
    for start in range(0, total, BATCH_SIZE):
        batch = records[start: start + BATCH_SIZE]
        index.upsert_records(namespace=namespace, records=batch)
        end = min(start + BATCH_SIZE, total)
        print(f"  Upserted {end}/{total} records into Pinecone")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    for key, val, label in [
        (PINECONE_API_KEY, PINECONE_API_KEY, "pinecone_api_key"),
        (SUPABASE_URL, SUPABASE_URL, "SUPABASE_URL"),
        (SUPABASE_SERVICE_KEY, SUPABASE_SERVICE_KEY, "SUPABASE_SERVICE_KEY"),
    ]:
        if not val or "YOUR_" in val:
            raise SystemExit(f"Missing or placeholder value for {label} in .env")

    sb    = get_supabase()
    pc    = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(INDEX_NAME)

    print("=== Setting up Supabase Storage bucket ===")
    ensure_bucket(sb)

    print("\n=== Processing Class 12 zip (uploading images + building records) ===")
    records_12 = process_zip(ZIP_CLASS12, "Class 12", sb)
    print(f"  → {len(records_12)} sections")

    print("\n=== Processing Class 11 zip (uploading images + building records) ===")
    records_11 = process_zip(ZIP_CLASS11, "Class 11", sb)
    print(f"  → {len(records_11)} sections")

    all_records = records_12 + records_11
    print(f"\n=== Upserting {len(all_records)} records into Pinecone ===")
    upsert_in_batches(index, NAMESPACE, all_records)

    stats = index.describe_index_stats()
    print(f"\n{'='*50}")
    print(f"DONE!")
    print(f"  Images uploaded OK  : {_upload_ok}")
    print(f"  Images failed       : {_upload_fail}")
    print(f"  Pinecone vectors    : {stats.total_vector_count}")
    print(f"  Storage bucket URL  : {SUPABASE_URL}/storage/v1/object/public/{BUCKET}/")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
