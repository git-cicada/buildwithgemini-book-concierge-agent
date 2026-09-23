# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
from zoneinfo import ZoneInfo

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.genai import types

from .a2ui_utils import a2ui_callback


async def generate_memories_callback(callback_context: CallbackContext):
    """Callback to persist session memories to Memory Bank after each turn."""
    await callback_context.add_session_to_memory()
    return None


# Hardcoded project ID string required for Agent Platform compatibility
FIRESTORE_PROJECT_ID = "qwiklabs-gcp-01-8ed423a30a4f"
MEDIA_BUCKET_NAME = "book-concierge-media-qwiklabs-gcp-01-8ed423a30a4f"


def _get_firestore_db():
    from google.cloud import firestore

    return firestore.Client(project=FIRESTORE_PROJECT_ID)


async def generate_cover_art(
    tool_context: ToolContext,
    prompt: str,
    title: str = "custom_book",
) -> dict:
    """Generate custom book cover art using generative AI, save it as a session artifact, and upload it to public Cloud Storage.

    Args:
        tool_context: The ADK ToolContext injected automatically at runtime.
        prompt: Visual description or style prompt for the book cover art (e.g., 'Minimalist sci-fi cover of desert dunes').
        title: Title of the book or filename identifier for saving the cover art.

    Returns:
        A status dictionary containing the public Cloud Storage image URL and artifact details.
    """
    import google.genai as genai
    from google.cloud import storage
    from google.genai import types

    # Generate image using gemini-3.1-flash-lite-image in global region
    client = genai.Client(vertexai=True, project=FIRESTORE_PROJECT_ID, location="global")
    full_prompt = f"Generate high quality book cover art for '{title}': {prompt}"
    response = client.models.generate_content(
        model="gemini-3.1-flash-lite-image",
        contents=full_prompt,
    )

    png_bytes = None
    if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type and part.inline_data.mime_type.startswith("image/"):
                png_bytes = part.inline_data.data
                break

    if not png_bytes:
        return {"status": "error", "message": "Failed to generate image bytes from prompt."}

    safe_title = "".join(c if c.isalnum() else "_" for c in title.lower())
    filename = f"{safe_title}_cover.png"
    blob_name = f"covers/{filename}"

    # 1. Save artifact in Playground's Artifacts panel via tool_context
    artifact_part = types.Part.from_bytes(data=png_bytes, mime_type="image/png")
    await tool_context.save_artifact(filename=filename, artifact=artifact_part)

    # 2. Upload same image bytes to public Cloud Storage bucket
    storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
    bucket = storage_client.bucket(MEDIA_BUCKET_NAME)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(png_bytes, content_type="image/png")

    public_url = f"https://storage.googleapis.com/{MEDIA_BUCKET_NAME}/{blob_name}"
    return {
        "status": "success",
        "message": f"Generated cover art for '{title}'",
        "artifact_saved": filename,
        "cover_url": public_url,
    }


def list_books(genre: str | None = None, status: str | None = None) -> list[dict]:
    """Retrieve books from the reading list / library stored in Firestore.

    Args:
        genre: Optional filter by genre (e.g. 'Sci-Fi', 'Fantasy').
        status: Optional filter by status ('Reading', 'Finished', 'Want to Read').

    Returns:
        List of book records with title, author, genre, current_page, total_pages, rating, notes.
    """
    db = _get_firestore_db()
    ref = db.collection("books")
    docs = ref.stream()
    books = []
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        if genre and data.get("genre", "").lower() != genre.lower():
            continue
        if status and data.get("status", "").lower() != status.lower():
            continue
        books.append(data)
    return books


def add_book(
    title: str,
    author: str,
    genre: str,
    total_pages: int,
    status: str = "Want to Read",
    current_page: int = 0,
    notes: str | None = None,
) -> dict:
    """Add a new book to the user's reading list in Firestore.

    Args:
        title: Title of the book.
        author: Author of the book.
        genre: Genre of the book (e.g. Sci-Fi, Fantasy, Mystery).
        total_pages: Total number of pages in the book.
        status: Reading status ('Want to Read', 'Reading', 'Finished'). Defaults to 'Want to Read'.
        current_page: Current page number read so far. Defaults to 0.
        notes: Optional initial reading notes.

    Returns:
        A status dictionary indicating success and saved book details.
    """
    db = _get_firestore_db()
    book_id = f"book-{title.lower().replace(' ', '-')}"
    data = {
        "title": title,
        "author": author,
        "genre": genre,
        "total_pages": total_pages,
        "current_page": current_page,
        "status": status,
        "rating": None,
        "notes": notes or "",
    }
    db.collection("books").document(book_id).set(data)
    data["id"] = book_id
    return {"status": "success", "message": f"Added '{title}' to reading list", "book": data}


def update_reading_bookmark(
    title: str,
    current_page: int,
    notes: str | None = None,
    status: str | None = None,
) -> dict:
    """Update the reading bookmark (current page, notes, status) for a book in Firestore.

    Args:
        title: The title (or title fragment) of the book to update.
        current_page: The new current page number.
        notes: Optional reading notes or bookmark comment.
        status: Optional updated status ('Reading', 'Finished', 'Want to Read').

    Returns:
        A dictionary with updated book details or an error message if not found.
    """
    db = _get_firestore_db()
    docs = db.collection("books").stream()
    matched_doc = None
    matched_data = None
    for doc in docs:
        d = doc.to_dict()
        if title.lower() in d.get("title", "").lower():
            matched_doc = doc.reference
            matched_data = d
            break

    if not matched_doc or not matched_data:
        return {"status": "error", "message": f"Book matching '{title}' not found in reading list."}

    updates = {"current_page": current_page}
    if notes is not None:
        updates["notes"] = notes
    if status is not None:
        updates["status"] = status
    elif current_page >= matched_data.get("total_pages", 1) and matched_data.get("total_pages", 0) > 0:
        updates["status"] = "Finished"

    matched_doc.update(updates)
    matched_data.update(updates)
    return {
        "status": "success",
        "message": f"Updated bookmark for '{matched_data['title']}' to page {current_page}",
        "book": matched_data,
    }


def search_public_books(query: str, limit: int = 5) -> list[dict]:
    """Search the Open Library public catalog for real book metadata by title, author, or topic.

    Args:
        query: Search term for the book title, author, or genre topic (e.g. 'Dune', 'Isaac Asimov', 'Sci-Fi').
        limit: Maximum number of search results to return (default 5).

    Returns:
        List of dictionaries containing title, author, first_publish_year, edition_count, and open_library_url.
    """
    import json
    import os
    import urllib.parse
    import urllib.request

    base_url = os.getenv("OPEN_LIBRARY_BASE_URL", "https://openlibrary.org/search.json")
    api_key = os.getenv("OPEN_LIBRARY_API_KEY", None)

    encoded_query = urllib.parse.quote(query)
    url = f"{base_url}?q={encoded_query}&limit={limit}"
    headers = {"User-Agent": "BookConciergeAgent/1.0"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            results = []
            for doc in data.get("docs", []):
                authors = doc.get("author_name", ["Unknown Author"])
                results.append(
                    {
                        "title": doc.get("title", "Untitled"),
                        "author": authors[0] if authors else "Unknown",
                        "first_publish_year": doc.get("first_publish_year"),
                        "edition_count": doc.get("edition_count", 1),
                        "key": doc.get("key"),
                        "open_library_url": f"https://openlibrary.org{doc.get('key')}" if doc.get("key") else None,
                    }
                )
            return results
    except Exception as e:
        return [{"status": "error", "message": f"Failed to search Open Library catalog: {str(e)}"}]


def get_weather(query: str) -> str:
    """Simulates a web search. Use it get information on weather.

    Args:
        query: A string containing the location to get weather information for.

    Returns:
        A string with the simulated weather information for the queried location.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        return "It's 60 degrees and foggy."
    return "It's 90 degrees and sunny."


def get_current_time(query: str) -> str:
    """Simulates getting the current time for a city.

    Args:
        query: The name of the city to get the current time for.

    Returns:
        A string with the current time information.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        tz_identifier = "America/Los_Angeles"
    else:
        return f"Sorry, I don't have timezone information for query: {query}."

    tz = ZoneInfo(tz_identifier)
    now = datetime.datetime.now(tz)
    return f"The current time for query {query} is {now.strftime('%Y-%m-%d %H:%M:%S %Z%z')}"


schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are a helpful Book Concierge AI assistant. You help readers manage their "
        "reading list, track bookmarks/page progress, discover real books from the public "
        "Open Library catalog, query stored books in Firestore, and generate custom book cover art."
    ),
    workflow_description="Analyze the user request, call function tools when appropriate, and return structured UI components.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        "{\"Image\": {\"url\": {\"literalString\": \"https://...\"}}}. Never point an "
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=instruction,
    tools=[
        PreloadMemoryTool(),
        list_books,
        add_book,
        update_reading_bookmark,
        generate_cover_art,
        search_public_books,
        get_weather,
        get_current_time,
    ],
    after_model_callback=a2ui_callback,
    after_agent_callback=generate_memories_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)
