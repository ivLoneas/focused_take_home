"""Resumable Silver artifacts. Publish metadata last; verify hashes on reuse."""

from dataclasses import asdict
from pathlib import Path
from typing import Any

from etl.chunking import chunk_blocks
from etl.manifest import verify_source
from etl.models import Block, Chunk
from etl.parsing import document_blocks
from etl.pictures import empty_usage, enrich_pictures
from utils import read_json, sha256_file, sha256_json, write_json

CHUNK_VERSION = 1


def read_chunks(path: Path) -> list[Chunk]:
    return [
        Chunk(**(row | {key: tuple(row[key]) for key in ("headings", "pages", "source_refs")}))
        for row in read_json(path)
    ]


def prepare_document(
    source,
    raw_dir,
    silver_dir,
    converter,
    parse_config,
    max_chars=1000,
    overlap=200,
    *,
    picture_client=None,
    picture_cache_dir: Path | None = None,
):
    """Verify one PDF, reuse valid Silver artifacts, and rebuild only stale stages."""

    if max_chars <= 0 or not 0 <= overlap < max_chars:
        raise ValueError("Require max_chars > overlap >= 0")
    pdf = verify_source(raw_dir, source)
    directory = silver_dir / source.document_id
    metadata_path = directory / "metadata.json"
    parse_key = sha256_json([source.sha256, source.pages, parse_config], compact=False)
    chunk_key = sha256_json([CHUNK_VERSION, max_chars, overlap], compact=False)
    metadata: dict[str, Any] = {}
    try:
        loaded_metadata = read_json(metadata_path)
        if isinstance(loaded_metadata, dict):
            metadata = loaded_metadata
    except OSError, ValueError:
        pass

    def valid(names):
        try:
            return all(sha256_file(directory / name) == metadata.get("hashes", {}).get(name) for name in names)
        except OSError:
            return False

    parse_files = ["document.json", "document.md", "blocks.json"]
    parsed = metadata.get("parse_key") == parse_key and valid(parse_files)
    if (
        parsed
        and metadata.get("chunk_key") == chunk_key
        and metadata.get("source") == asdict(source)
        and valid(["chunks.json"])
    ):
        return directory, True

    directory.mkdir(parents=True, exist_ok=True)
    # Metadata is the completion marker, so removing it makes interrupted rebuilds unusable.
    metadata_path.unlink(missing_ok=True)
    picture_usage = metadata.get("picture_usage", empty_usage())
    if parsed:
        blocks = [
            Block(**(row | {key: tuple(row[key]) for key in ("headings", "pages")}))
            for row in read_json(directory / "blocks.json")
        ]
    else:
        from docling.datamodel.base_models import ConversionStatus

        result = converter.convert(pdf)
        if result.status != ConversionStatus.SUCCESS:
            raise ValueError(f"Docling conversion did not fully succeed: {result.status}")
        doc = result.document
        if len(doc.pages) != source.pages:
            raise ValueError(f"Page count mismatch: expected {source.pages}, parsed {len(doc.pages)}")
        picture_usage = empty_usage()
        if parse_config.get("pictures"):
            if picture_client is None or picture_cache_dir is None:
                raise ValueError("Picture enrichment requires an OpenAI client and cache directory")
            picture_usage = enrich_pictures(doc, picture_client, picture_cache_dir)
        blocks = document_blocks(doc)
        write_json(directory / "document.json", doc.export_to_dict())
        (directory / "document.md").write_text(doc.export_to_markdown(), encoding="utf-8")
        write_json(directory / "blocks.json", [asdict(block) for block in blocks])
    chunks = chunk_blocks(source.document_id, blocks, max_chars, overlap)
    if not chunks:
        raise ValueError("Empty extraction: no retrieval chunks produced")
    write_json(directory / "chunks.json", [asdict(chunk) for chunk in chunks])
    metadata = {
        "source": asdict(source),
        "parse_config": parse_config,
        "parse_key": parse_key,
        "chunk_key": chunk_key,
        "max_chars": max_chars,
        "overlap": overlap,
        "chunk_count": len(chunks),
        "block_count": len(blocks),
        "picture_usage": picture_usage,
        "hashes": {name: sha256_file(directory / name) for name in [*parse_files, "chunks.json"]},
    }
    write_json(metadata_path, metadata)
    return directory, False
