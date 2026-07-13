"""Splits markdown into heading-scoped chunks so citations can point back
to a meaningful section (e.g. 'Setup > Installation') rather than an
arbitrary character offset."""
import re
from dataclasses import dataclass

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)
_MAX_CHUNK_CHARS = 1500


@dataclass
class Chunk:
    heading_path: str | None
    content: str


def chunk_markdown(text: str) -> list[Chunk]:
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return _split_long(text.strip(), heading_path=None)

    chunks: list[Chunk] = []
    heading_stack: list[tuple[int, str]] = []

    for i, match in enumerate(matches):
        level = len(match.group(1))
        title = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()

        heading_stack = [h for h in heading_stack if h[0] < level]
        heading_stack.append((level, title))
        heading_path = " > ".join(h[1] for h in heading_stack)

        if body:
            chunks.extend(_split_long(body, heading_path))

    return chunks


def _split_long(body: str, heading_path: str | None) -> list[Chunk]:
    if len(body) <= _MAX_CHUNK_CHARS:
        return [Chunk(heading_path=heading_path, content=body)]

    parts = []
    for i in range(0, len(body), _MAX_CHUNK_CHARS):
        parts.append(Chunk(heading_path=heading_path, content=body[i : i + _MAX_CHUNK_CHARS]))
    return parts
