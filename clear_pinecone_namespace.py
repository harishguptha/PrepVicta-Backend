"""
Delete all Pinecone records from one namespace so ingestion can be rerun.

Run:
    python clear_pinecone_namespace.py --confirm

Optional:
    python clear_pinecone_namespace.py --index prepvictes --namespace neet-biology --confirm
"""

import argparse
import os

from dotenv import load_dotenv
from pinecone import Pinecone
from pinecone.openapi_support.exceptions import NotFoundException


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delete all records from a Pinecone namespace."
    )
    parser.add_argument("--index", default=os.getenv("PINECONE_INDEX", ""))
    parser.add_argument("--namespace", default=os.getenv("PINECONE_NAMESPACE", ""))
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually delete records. Without this flag the script is a dry run.",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()

    api_key = os.getenv("PINECONE_API_KEY", os.getenv("pinecone_api_key", ""))
    if not api_key:
        raise SystemExit("Missing PINECONE_API_KEY or pinecone_api_key in .env")
    if not args.index:
        raise SystemExit("Missing Pinecone index. Set PINECONE_INDEX or pass --index.")
    if not args.namespace:
        raise SystemExit(
            "Missing Pinecone namespace. Set PINECONE_NAMESPACE or pass --namespace."
        )

    pc = Pinecone(api_key=api_key)
    index = pc.Index(args.index)

    before = index.describe_index_stats()
    print(f"Index: {args.index}")
    print(f"Namespace: {args.namespace}")
    print(f"Vectors before delete: {before.total_vector_count}")

    if not args.confirm:
        print("Dry run only. Re-run with --confirm to delete this namespace.")
        return

    try:
        index.delete(delete_all=True, namespace=args.namespace)
    except NotFoundException as exc:
        if "Namespace not found" in str(exc):
            print("Namespace is already empty or does not exist.")
            return
        raise

    after = index.describe_index_stats()
    print("Delete request sent.")
    print(f"Vectors after delete: {after.total_vector_count}")


if __name__ == "__main__":
    main()
