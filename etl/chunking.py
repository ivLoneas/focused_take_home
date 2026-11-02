"""Character-budget chunks inside Docling section boundaries, with provenance."""

import json

from etl.models import Block, Chunk
from utils import sha256_text


def windows(text: str, size: int, overlap: int):
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            # Prefer paragraph/sentence/word breaks, but always advance beyond overlap.
            floor = start + max(overlap + 1, size // 2)
            for separator in ("\n\n", ". ", " "):
                boundary = text.rfind(separator, floor, end)
                if boundary >= floor:
                    end = boundary + len(separator)
                    break
        yield start, end, text[start:end]
        if end == len(text):
            break
        start = end - overlap


def table_parts(block: Block, size: int, overlap: int):
    header = block.table_header
    if not header or len(header) + 2 >= size:
        # A header wider than the budget cannot be repeated; keep all text.
        yield from (part for _, _, part in windows(block.text, size, overlap))
        return
    body = block.text[len(header) :].lstrip("\n") if block.text.startswith(header) else block.text
    budget = size - len(header) - 1
    rows, current = body.splitlines(), []
    for row in rows:
        if len(row) > budget:
            if current:
                yield header + "\n" + "\n".join(current)
                current = []
            for _, _, part in windows(row, budget, min(overlap, budget - 1)):
                yield header + "\n" + part
        elif len("\n".join([*current, row])) > budget:
            yield header + "\n" + "\n".join(current)
            # Row overlap is bounded; do not split a row merely to obtain overlap.
            tail = []
            for previous in reversed(current):
                candidate = [previous, *tail]
                if len("\n".join(candidate)) > overlap:
                    break
                tail = candidate
            while tail and len("\n".join([*tail, row])) > budget:
                tail.pop(0)
            current = [*tail, row]
        else:
            current.append(row)
    if current:
        yield header + "\n" + "\n".join(current)
    elif not rows:
        yield header


def chunk_blocks(document_id: str, blocks: list[Block], max_chars: int = 1000, overlap: int = 200) -> list[Chunk]:
    """Chunk within section boundaries while keeping table structure and source provenance."""

    if max_chars <= 0 or not 0 <= overlap < max_chars:
        raise ValueError("Require max_chars > overlap >= 0")
    chunks = []

    def emit(text, members):
        if not text.strip():
            return
        headings, kind = members[0].headings, members[0].kind
        pages = tuple(sorted({page for block in members for page in block.pages}))
        refs = tuple(dict.fromkeys(block.ref for block in members if block.ref))
        ordinal = len(chunks)
        identity = json.dumps([document_id, ordinal, text, headings, pages, refs, kind], ensure_ascii=False)
        chunks.append(Chunk(sha256_text(identity), document_id, ordinal, text, headings, pages, refs, kind))

    def flush(group):
        if not group:
            return
        text, spans = "", []
        for block in group:
            if text:
                text += "\n\n"
            start = len(text)
            text += block.text.strip()
            spans.append((start, len(text), block))
        for start, end, part in windows(text, max_chars, overlap):
            emit(part, [block for left, right, block in spans if left < end and right > start])

    group = []
    for block in blocks:
        if not block.text.strip():
            continue
        if block.kind != "text":
            flush(group)
            group = []
            parts = (
                table_parts(block, max_chars, overlap)
                if block.kind == "table"
                else (part for _, _, part in windows(block.text, max_chars, overlap))
            )
            for part in parts:
                emit(part, [block])
        else:
            if group and group[-1].headings != block.headings:
                flush(group)
                group = []
            group.append(block)
    flush(group)
    return chunks
