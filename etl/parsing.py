"""Docling layout, heading hierarchy, tables, OCR, and picture rendering."""
import os
from importlib.metadata import version
from pathlib import Path

from etl.models import Block

IMAGE_PROMPT = (
    "Describe this financial-report figure briefly. Include visible chart title, axes, "
    "units, periods and trends. Transcribe values only if clearly legible. Do not infer "
    "missing numbers or use outside knowledge. Say when content is unreadable."
)


def parser_config(pictures: bool = True) -> dict:
    return {"version": 1, "docling": version("docling"), "docling_core": version("docling-core"),
            "heading_hierarchy": True, "ocr": "rapidocr-torch", "tables": "accurate",
            "pictures": pictures, "picture_model": "gpt-6-luna",
            "picture_prompt": IMAGE_PROMPT, "picture_detail": "high", "images_scale": 2.0}


def build_converter(pictures: bool = True):
    """Configure hierarchy, OCR, tables, and optional picture crops for API enrichment."""

    # Docling interprets DOCLING_ARTIFACTS_PATH as a complete offline model
    # bundle. An empty persistent cache on the first container run is not one.
    artifact_setting = os.environ.get("DOCLING_ARTIFACTS_PATH")
    if artifact_setting:
        artifact_path = Path(artifact_setting)
        if not artifact_path.is_dir() or not any(artifact_path.iterdir()):
            os.environ.pop("DOCLING_ARTIFACTS_PATH")
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        HeadingHierarchyOptions,
        PdfPipelineOptions,
        RapidOcrOptions,
        TableFormerMode,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions()
    options.heading_hierarchy_options = HeadingHierarchyOptions(enabled=True)
    options.do_ocr = True
    options.ocr_options = RapidOcrOptions(backend="torch")
    options.do_table_structure = True
    options.table_structure_options.mode = TableFormerMode.ACCURATE
    options.table_structure_options.do_cell_matching = True
    options.do_picture_description = False
    options.generate_picture_images = pictures
    options.images_scale = 2.0
    return DocumentConverter(allowed_formats=[InputFormat.PDF], format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=options),
    })


def compact_table(item, doc) -> tuple[str, str]:
    # Docling resolves merged/multirow cells in its dataframe exporter. Avoid
    # Markdown padding, which wastes the small baseline character budget.
    frame = item.export_to_dataframe(doc=doc)
    def row(values):
        return "| " + " | ".join(str(value).replace("\n", " ").replace("|", "\\|") for value in values) + " |"
    if not len(frame.columns):
        return "", ""
    header = row(frame.columns) + "\n" + row(["---"] * len(frame.columns))
    body = "\n".join(row(values) for values in frame.itertuples(index=False, name=None))
    caption = item.caption_text(doc)
    if caption:
        header = caption + "\n" + header
    return header + ("\n" + body if body else ""), header


def document_blocks(doc) -> list[Block]:
    """Flatten Docling items into retrieval blocks while preserving hierarchy and provenance."""

    from docling_core.types.doc import PictureItem, SectionHeaderItem, TableItem, TextItem

    blocks, stack = [], []
    title = ""
    # Picture groups can contain OCR text and tables that are otherwise skipped.
    for item, _ in doc.iterate_items(traverse_pictures=True):
        label = getattr(item, "label", "")
        if label in {"page_header", "page_footer"}:
            continue
        if label == "title":
            title, stack = item.text.strip(), []
            continue
        if isinstance(item, SectionHeaderItem):
            while stack and stack[-1][0] >= item.level:
                stack.pop()
            stack.append((item.level, item.text.strip()))
            continue
        headings = tuple(([title] if title else []) + [text for _, text in stack if text])
        pages = tuple(sorted({prov.page_no for prov in item.prov}))
        text, kind, header = "", "text", ""
        if isinstance(item, TableItem):
            text, header = compact_table(item, doc)
            kind = "table"
        elif isinstance(item, PictureItem):
            kind = "picture"
            text = item.caption_text(doc)
            description = item.meta.description if item.meta else None
            if description and description.text.strip():
                text += "\n[Generated image description; verify against source]\n" + description.text
        elif isinstance(item, TextItem):
            text = item.text
        if text.strip():
            blocks.append(Block(text.strip(), kind, headings, pages, item.self_ref, header))
    return blocks
