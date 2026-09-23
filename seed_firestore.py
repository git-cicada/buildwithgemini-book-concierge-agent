"""Seed script for Firestore books collection."""

import os
import subprocess
from google.cloud import firestore
from google.oauth2 import credentials

# IMPORTANT: Hardcoded Project ID string as required for Agent Platform compatibility
FIRESTORE_PROJECT_ID = "qwiklabs-gcp-01-8ed423a30a4f"

INITIAL_BOOKS = [
    {
        "id": "book-1",
        "title": "Dune",
        "author": "Frank Herbert",
        "genre": "Sci-Fi",
        "status": "Reading",
        "current_page": 142,
        "total_pages": 412,
        "rating": 4.8,
        "notes": "Chapter 6 - Arrakis arrival.",
    },
    {
        "id": "book-2",
        "title": "Project Hail Mary",
        "author": "Andy Weir",
        "genre": "Sci-Fi",
        "status": "Finished",
        "current_page": 496,
        "total_pages": 496,
        "rating": 5.0,
        "notes": "Loved Ryland and Rocky's partnership!",
    },
    {
        "id": "book-3",
        "title": "The Hobbit",
        "author": "J.R.R. Tolkien",
        "genre": "Fantasy",
        "status": "Want to Read",
        "current_page": 0,
        "total_pages": 310,
        "rating": None,
        "notes": "Next up on the reading list.",
    },
    {
        "id": "book-4",
        "title": "Mistborn: The Final Empire",
        "author": "Brandon Sanderson",
        "genre": "Fantasy",
        "status": "Reading",
        "current_page": 215,
        "total_pages": 541,
        "rating": 4.9,
        "notes": "Vin is learning Allomancy.",
    },
]


def get_firestore_client() -> firestore.Client:
    """Initialize Firestore client using hardcoded project ID string."""
    try:
        token = subprocess.check_output(
            ["gcloud", "auth", "print-access-token"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        creds = credentials.Credentials(token)
        return firestore.Client(project=FIRESTORE_PROJECT_ID, credentials=creds)
    except Exception:
        return firestore.Client(project=FIRESTORE_PROJECT_ID)


def seed_database():
    """Seed the books collection in Firestore."""
    db = get_firestore_client()
    collection_ref = db.collection("books")

    print(f"Seeding Firestore collection 'books' in project '{FIRESTORE_PROJECT_ID}'...")
    for book in INITIAL_BOOKS:
        doc_id = book["id"]
        data = {k: v for k, v in book.items() if k != "id"}
        collection_ref.document(doc_id).set(data)
        print(f"  - Seeded book '{book['title']}' (ID: {doc_id})")

    print("Seeding complete! ✅")


if __name__ == "__main__":
    seed_database()
