from dataclasses import dataclass


@dataclass(frozen=True)
class SourceDocument:
    document_id: str
    path: str
    sha256: str
    company: str
    fiscal_year: int
    quarter: str
    report_type: str
    title: str
    url: str
    pages: int


@dataclass(frozen=True)
class Block:
    text: str
    kind: str = "text"
    headings: tuple[str, ...] = ()
    pages: tuple[int, ...] = ()
    ref: str = ""
    table_header: str = ""


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document_id: str
    ordinal: int
    text: str
    headings: tuple[str, ...]
    pages: tuple[int, ...]
    source_refs: tuple[str, ...]
    kind: str
