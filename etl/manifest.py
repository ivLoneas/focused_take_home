"""Use the existing inventory as the only source of reporting metadata."""

import csv
import re
from pathlib import Path

from etl.models import SourceDocument
from utils import sha256_file, sha256_text


def source_path(raw_dir: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or path.suffix.lower() != ".pdf":
        raise ValueError(f"Unsafe/non-PDF source path: {relative}")
    resolved = (raw_dir / path).resolve()
    if not resolved.is_relative_to(raw_dir.resolve()):
        raise ValueError(f"Source escapes raw directory: {relative}")
    return resolved


def load_manifest(raw_dir: Path, *, manifest_path: Path | None = None) -> list[SourceDocument]:
    """Validate the inventory and confine every referenced PDF beneath the raw directory."""

    sources, seen = [], set()
    inventory = manifest_path if manifest_path is not None else raw_dir / "manifest.csv"
    with inventory.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        required = {"company", "fiscal_year", "quarter", "report_type", "title", "path", "pages", "sha256", "url"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Manifest is missing required columns")
        for row in reader:
            if any(not row.get(key) for key in required - {"quarter", "url"}):
                raise ValueError("Manifest contains empty required metadata")
            path = source_path(raw_dir, row["path"])
            if path in seen:
                raise ValueError(f"Duplicate source path: {row['path']}")
            seen.add(path)
            year, pages = int(row["fiscal_year"]), int(row["pages"])
            if not 1900 <= year <= 2200 or pages <= 0:
                raise ValueError("Invalid fiscal year or page count")
            if row["quarter"] not in {"", "1", "2", "3", "4"}:
                raise ValueError("Invalid fiscal quarter")
            if not re.fullmatch(r"[a-fA-F0-9]{64}", row["sha256"]):
                raise ValueError("Invalid source SHA-256")
            sources.append(
                SourceDocument(
                    document_id=sha256_text(row["path"]),
                    path=row["path"],
                    sha256=row["sha256"].lower(),
                    company=row["company"],
                    fiscal_year=year,
                    quarter=row["quarter"],
                    report_type=row["report_type"],
                    title=row["title"],
                    url=row["url"],
                    pages=pages,
                )
            )
    return sources


def verify_source(raw_dir: Path, source: SourceDocument) -> Path:
    path = source_path(raw_dir, source.path)
    with path.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise ValueError(f"Not a PDF: {source.path}")
    digest = sha256_file(path)
    if digest != source.sha256:
        raise ValueError(f"Source checksum mismatch: {source.path}")
    return path
