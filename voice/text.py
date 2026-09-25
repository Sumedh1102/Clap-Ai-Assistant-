"""Text preparation for speech: strip markdown and split into speakable chunks."""

from __future__ import annotations

import re


def strip_markdown(text: str) -> str:
    """Remove markdown so TTS reads naturally."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)       # bold
    text = re.sub(r"\*(.+?)\*", r"\1", text)             # italic
    text = re.sub(r"__(.+?)__", r"\1", text)             # bold alt
    text = re.sub(r"`{1,3}[^`]*`{1,3}", "", text)        # code
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)   # headers
    text = re.sub(r"^[ \t]*[-*+][ \t]+", "", text, flags=re.M)  # bullets (keep blank lines)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # markdown links
    text = re.sub(r"https?://\S+", "a link", text)        # URLs
    text = re.sub(r"\n{2,}", ". ", text)
    text = re.sub(r"\n", " ", text)
    text = re.sub(r"\.\s*\.", ".", text)
    return text.strip()


def split_for_speech(text: str, max_chars: int = 600) -> list[str]:
    """
    Split text into chunks on sentence boundaries, each at most max_chars, so
    the first chunk can start playing while the next is being synthesised.
    """
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        while len(sentence) > max_chars:  # pathological run-on sentence
            cut = sentence.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            if current:
                chunks.append(current)
                current = ""
            chunks.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if current and len(current) + 1 + len(sentence) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks
