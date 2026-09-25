"""
Knowledge base — SQLite FTS5 full-text search.

Stores notes, documents, and imported Claude conversations that
CLAP can search during conversations for additional context.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from database import get_conn


def _make_id(content: str) -> str:
    ts = datetime.now().isoformat(timespec="microseconds")
    return hashlib.md5(f"{content}{ts}".encode()).hexdigest()[:16]


# ── CRUD ─────────────────────────────────────────────────────────────────────

def add_knowledge(
    content: str,
    title: str = "",
    source: str = "manual",
    tags: str = "",
) -> dict:
    """Add a document to the knowledge base."""
    if not content.strip():
        return {"success": False, "error": "Content cannot be empty"}
    doc_id = _make_id(content)
    title = title.strip() or content[:60].replace("\n", " ")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO knowledge (id, title, content, source, tags) VALUES (?,?,?,?,?)",
            (doc_id, title, content, source, tags),
        )
    return {"success": True, "id": doc_id, "message": f"Saved to knowledge base: {title}"}


def search_knowledge(query: str, n_results: int = 5) -> dict:
    """Full-text search the knowledge base. Returns ranked results."""
    if not query.strip():
        return {"success": False, "error": "Query cannot be empty"}
    n_results = max(1, min(n_results, 20))
    with get_conn() as conn:
        # Check if anything is indexed
        count = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        if count == 0:
            return {"success": True, "results": [], "message": "Knowledge base is empty"}
        try:
            rows = conn.execute(
                """
                SELECT id, title,
                       snippet(knowledge_fts, 2, '[', ']', '...', 24) AS excerpt,
                       source, tags, added_at, rank
                FROM knowledge_fts
                WHERE knowledge_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, n_results),
            ).fetchall()
        except Exception:
            # FTS MATCH can throw on malformed queries — fall back to LIKE
            rows = conn.execute(
                """
                SELECT id, title, substr(content,1,200) AS excerpt,
                       source, tags, added_at, 0 AS rank
                FROM knowledge
                WHERE content LIKE ? OR title LIKE ?
                LIMIT ?
                """,
                (f"%{query}%", f"%{query}%", n_results),
            ).fetchall()
    results = [dict(r) for r in rows]
    return {"success": True, "results": results, "count": len(results)}


def list_knowledge(limit: int = 50) -> dict:
    """List knowledge base entries (most recent first)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, source, tags, added_at, substr(content,1,120) AS preview "
            "FROM knowledge ORDER BY added_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {"success": True, "items": [dict(r) for r in rows], "total": len(rows)}


def delete_knowledge(doc_id: str) -> dict:
    """Delete a knowledge base entry by ID."""
    with get_conn() as conn:
        conn.execute("DELETE FROM knowledge WHERE id = ?", (doc_id,))
    return {"success": True, "message": f"Deleted entry {doc_id}"}


# ── Importers ─────────────────────────────────────────────────────────────────

def import_claude_conversation(json_text: str, title: str = "") -> dict:
    """
    Import a Claude.ai conversation export (JSON) into the knowledge base.
    Accepts the array-of-messages format exported from Claude.ai.
    """
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        return {"success": False, "error": f"Invalid JSON: {exc}"}

    # Normalise to list of {role, content} dicts
    messages: list[dict] = []
    if isinstance(data, list):
        messages = data
    elif isinstance(data, dict):
        messages = data.get("messages", data.get("conversation", []))

    if not messages:
        return {"success": False, "error": "No messages found in the export"}

    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", msg.get("sender", "unknown")).upper()
        content = msg.get("content", "")
        if isinstance(content, list):
            # Claude API block format
            content = " ".join(
                c.get("text", "") for c in content if isinstance(c, dict)
            )
        if content:
            parts.append(f"{role}: {content.strip()}")

    full_text = "\n\n".join(parts)
    if not full_text:
        return {"success": False, "error": "Conversation appears empty"}

    conv_title = title or f"Claude conversation {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    chunk_size = 2000
    chunks_added = 0
    for i in range(0, len(full_text), chunk_size):
        chunk = full_text[i : i + chunk_size]
        part_num = i // chunk_size + 1
        result = add_knowledge(
            chunk,
            title=f"{conv_title} [part {part_num}]",
            source="claude_export",
            tags="conversation",
        )
        if result["success"]:
            chunks_added += 1

    return {
        "success": True,
        "message": f"Imported {chunks_added} chunk(s) from: {conv_title}",
    }


def import_file(file_path: str, title: str = "") -> dict:
    """Import a .txt, .md, or .pdf file into the knowledge base."""
    path = Path(file_path)
    if not path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            import pypdf  # type: ignore
            reader = pypdf.PdfReader(str(path))
            text = "\n".join(
                page.extract_text() or "" for page in reader.pages
            )
        except ImportError:
            return {"success": False, "error": "pypdf not installed — run: pip install pypdf"}
    else:
        text = path.read_text(encoding="utf-8", errors="replace")

    if not text.strip():
        return {"success": False, "error": "File appears empty"}

    return add_knowledge(text, title=title or path.name, source=str(path))
