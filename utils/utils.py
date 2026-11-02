"""Atomic I/O, hashing, validation, ordering, and prompt formatting."""

import csv
import hashlib
import json
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import SecretStr


class Evidence(Protocol):
    @property
    def source(self) -> str: ...

    @property
    def text(self) -> str: ...

    @property
    def metadata(self) -> Mapping[str, Any]: ...


type CsvQuoting = Literal[0, 1, 2, 3, 4, 5]


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_json(value: object, *, compact: bool = True) -> str:
    if compact:
        return sha256_bytes(canonical_json_bytes(value))
    serialized = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return sha256_text(serialized)


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object, *, indent: int | None = 2) -> None:
    """Atomically write UTF-8 JSON, preserving any destination on failure."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            separators = (",", ":") if indent is None else None
            json.dump(
                value,
                stream,
                ensure_ascii=False,
                indent=indent,
                separators=separators,
                allow_nan=False,
            )
            stream.write("\n")
        temporary.replace(path)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def write_csv(
    path: Path,
    rows: Iterable[Mapping[str, object]],
    *,
    fieldnames: Sequence[str],
    quoting: CsvQuoting = csv.QUOTE_MINIMAL,
    extrasaction: Literal["raise", "ignore"] = "raise",
) -> None:
    """Atomically write mapping rows as a UTF-8 CSV document."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            newline="",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            writer = csv.DictWriter(
                stream,
                fieldnames=fieldnames,
                quoting=quoting,
                extrasaction=extrasaction,
            )
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def normalize_optional_string(value: object) -> object:
    if isinstance(value, SecretStr):
        value = value.get_secret_value()
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def require_nonblank_string(value: object, *, field_name: str = "value") -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must not be blank")
    return value


def financial_report_sort_key(report: object) -> tuple[str, int, int, str]:
    def field(name: str) -> Any:
        if isinstance(report, Mapping):
            return report[name]
        return getattr(report, name)

    quarter_value = field("quarter")
    quarter_text = "" if quarter_value is None else str(quarter_value).strip().upper()
    quarter = 5 if quarter_text in {"", "ANNUAL", "FY"} else int(quarter_text.removeprefix("Q"))
    return str(field("company")), int(field("fiscal_year")), quarter, str(field("path"))


def format_bullets(items: Sequence[str], *, empty: str = "- No explicit fact list supplied") -> str:
    return "\n".join(f"- {item}" for item in items) or empty


def format_evidence(chunks: Sequence[Evidence], *, empty: str = "No evidence was retrieved.") -> str:
    if not chunks:
        return empty
    sections = []
    for chunk in chunks:
        metadata = ", ".join(f"{key}={value}" for key, value in sorted(chunk.metadata.items()))
        suffix = f" ({metadata})" if metadata else ""
        sections.append(f"Source: {chunk.source}{suffix}\n{chunk.text}")
    return "\n\n".join(sections)
