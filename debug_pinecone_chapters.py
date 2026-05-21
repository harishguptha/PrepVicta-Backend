"""
Run this to see what Chemistry chapter names are stored in Pinecone.
Usage: python debug_pinecone_chapters.py
"""
import asyncio
from dotenv import load_dotenv
load_dotenv()

from pinecone import Pinecone
from pinecone.data.dataclasses.search_query import SearchQuery
from app.config import get_settings

settings = get_settings()


def main():
    pc = Pinecone(api_key=settings.pinecone_api_key)
    index = pc.Index(settings.pinecone_index)

    print("=== Chemistry chapters in Pinecone ===\n")
    results = index.search_records(
        namespace=settings.pinecone_namespace,
        query=SearchQuery(
            inputs={"text": "chemistry organic reaction"},
            top_k=100,
            filter={"subject": {"$eq": "Chemistry"}},
        ),
        fields=["chapter", "section", "subject"],
    )

    chapters: dict[str, list[str]] = {}
    for hit in results.result.hits:
        ch = hit.fields.get("chapter", "<no chapter>")
        sec = hit.fields.get("section", "")
        chapters.setdefault(ch, []).append(sec)

    if not chapters:
        print("NO Chemistry records found in Pinecone.")
        print("Chemistry data may not have been ingested yet.")
    else:
        print(f"Found {len(chapters)} unique chapter(s):\n")
        for ch, secs in sorted(chapters.items()):
            print(f"  [{repr(ch)}]  ({len(secs)} sections)")

    print("\n=== Searching specifically for Aldehydes chapter ===\n")
    for query_ch in [
        "Aldehydes, Ketones & Carboxylic Acids",
        "Aldehydes, Ketones and Carboxylic Acids",
        "Aldehydes Ketones Carboxylic Acids",
    ]:
        r2 = index.search_records(
            namespace=settings.pinecone_namespace,
            query=SearchQuery(
                inputs={"text": query_ch},
                top_k=5,
                filter={"chapter": {"$eq": query_ch}, "subject": {"$eq": "Chemistry"}},
            ),
            fields=["chapter", "section"],
        )
        hits = r2.result.hits
        print(f"Filter chapter={repr(query_ch)}: {len(hits)} hit(s)")
        for h in hits:
            print(f"  → chapter={repr(h.fields.get('chapter'))}, section={repr(h.fields.get('section'))}")


if __name__ == "__main__":
    main()
