"""Adapter behavior against genuine Docling document types, without PDF models."""

import pytest

pytest.importorskip("docling_core")

from docling_core.types.doc import BoundingBox, DoclingDocument
from docling_core.types.doc.document import (
    DescriptionMetaField,
    DocItemLabel,
    PictureMeta,
    ProvenanceItem,
    TableCell,
    TableData,
)

from etl.parsing import document_blocks


def provenance(page=1):
    return ProvenanceItem(page_no=page, bbox=BoundingBox(l=0, t=0, r=100, b=20), charspan=(0, 10))


def test_nested_heading_levels_and_siblings_keep_title_context():
    doc = DoclingDocument(name="report")
    doc.add_title("Annual report")
    doc.add_heading("Results", level=1)
    doc.add_heading("Revenue", level=2)
    first = doc.add_text(DocItemLabel.TEXT, "Revenue was 100.", prov=provenance(2))
    doc.add_heading("Margins", level=2)
    doc.add_text(DocItemLabel.TEXT, "Margin was 20%.", prov=provenance(3))
    doc.add_heading("Risk", level=1)
    doc.add_text(DocItemLabel.TEXT, "Currency risk.", prov=provenance(4))
    blocks = document_blocks(doc)
    revenues = next(block for block in blocks if block.text == "Revenue was 100.")
    assert revenues.headings == ("Annual report", "Results", "Revenue")
    assert revenues.pages == (2,)
    assert revenues.ref == first.self_ref
    assert next(block for block in blocks if block.text == "Margin was 20%.").headings == ("Annual report", "Results", "Margins")
    assert next(block for block in blocks if block.text == "Currency risk.").headings == ("Annual report", "Risk")


def test_skipped_heading_levels_do_not_create_invented_headings():
    doc = DoclingDocument(name="report")
    doc.add_heading("Overview", level=1)
    doc.add_heading("Detail", level=3)
    doc.add_text(DocItemLabel.TEXT, "Details")
    doc.add_heading("Next", level=2)
    doc.add_text(DocItemLabel.TEXT, "Next details")
    blocks = document_blocks(doc)
    assert next(block for block in blocks if block.text == "Details").headings == ("Overview", "Detail")
    assert next(block for block in blocks if block.text == "Next details").headings == ("Overview", "Next")


def test_excludes_page_furniture_and_retains_list_content():
    doc = DoclingDocument(name="report")
    doc.add_text(DocItemLabel.PAGE_HEADER, "Repeated company header")
    doc.add_text(DocItemLabel.PAGE_FOOTER, "Page 20")
    doc.add_text(DocItemLabel.TEXT, "Body paragraph")
    group = doc.add_list_group()
    doc.add_list_item("First material risk", marker="-", parent=group, prov=provenance(2))
    blocks = document_blocks(doc)
    combined = "\n".join(block.text for block in blocks)
    assert "Repeated company header" not in combined
    assert "Page 20" not in combined
    assert "Body paragraph" in combined
    assert "First material risk" in combined
    assert next(block for block in blocks if "First material risk" in block.text).pages == (2,)


def test_table_keeps_column_headers_values_and_provenance():
    doc = DoclingDocument(name="report")
    doc.add_heading("Financial statements", level=1)
    cells = [
        TableCell(text=value, start_row_offset_idx=row, end_row_offset_idx=row + 1,
                  start_col_offset_idx=col, end_col_offset_idx=col + 1, column_header=row == 0)
        for row, values in enumerate([("Metric", "2025", "2024"), ("Net income", "100", "90")])
        for col, value in enumerate(values)
    ]
    item = doc.add_table(TableData(num_rows=2, num_cols=3, table_cells=cells), prov=provenance(7))
    blocks = document_blocks(doc)
    table = next(block for block in blocks if block.kind == "table")
    assert "Metric" in table.table_header and "2025" in table.table_header and "2024" in table.table_header
    assert "Net income" in table.text and "100" in table.text and "90" in table.text
    assert table.text.startswith(table.table_header)
    assert table.headings == ("Financial statements",)
    assert table.pages == (7,)
    assert table.ref == item.self_ref


def test_generated_image_description_is_explicitly_labeled():
    doc = DoclingDocument(name="report")
    doc.add_heading("Performance", level=1)
    picture = doc.add_picture(prov=provenance(3))
    picture.meta = PictureMeta(description=DescriptionMetaField(text="Bars rise from 2024 to 2025."))
    blocks = document_blocks(doc)
    image = next(block for block in blocks if block.kind == "picture")
    assert "[Generated image description; verify against source]" in image.text
    assert "Bars rise from 2024 to 2025." in image.text
    assert image.headings == ("Performance",)
    assert image.pages == (3,)
    assert image.ref == picture.self_ref


def test_picture_caption_is_retained_without_invented_description():
    doc = DoclingDocument(name="report")
    caption = doc.add_text(DocItemLabel.CAPTION, "Figure 1: Sales by region")
    doc.add_picture(caption=caption, prov=provenance(5))
    blocks = document_blocks(doc)
    content = "\n".join(block.text for block in blocks)
    assert "Figure 1: Sales by region" in content
    assert "[Generated image description" not in content


def test_empty_picture_and_empty_document_do_not_invent_content():
    doc = DoclingDocument(name="report")
    assert document_blocks(doc) == []
    doc.add_picture(prov=provenance())
    assert document_blocks(doc) == []


def test_text_detected_inside_picture_is_not_lost():
    doc = DoclingDocument(name="report")
    doc.add_heading("Sales", level=1)
    picture = doc.add_picture(prov=provenance(2))
    doc.add_text(DocItemLabel.TEXT, "Revenue: $1,234 million", parent=picture, prov=provenance(2))
    blocks = document_blocks(doc)
    extracted = next(block for block in blocks if "Revenue: $1,234 million" in block.text)
    assert extracted.pages == (2,)
    assert extracted.headings == ("Sales",)
    assert "Generated image description" not in extracted.text


def test_financial_footnotes_and_exact_numeric_formatting_are_retained():
    doc = DoclingDocument(name="report")
    doc.add_text(DocItemLabel.FOOTNOTE, "(1) Amounts in millions, except per-share data.", prov=provenance(8))
    values = [("Metric", "2025"), ("Loss", "(1,234.50)"), ("EPS", "$0.0100"), ("Change", "−12.5%"), ("Missing", "—")]
    cells = [TableCell(text=value, start_row_offset_idx=row, end_row_offset_idx=row + 1, start_col_offset_idx=col, end_col_offset_idx=col + 1, column_header=row == 0) for row, items in enumerate(values) for col, value in enumerate(items)]
    doc.add_table(TableData(num_rows=len(values), num_cols=2, table_cells=cells), prov=provenance(8))
    content = "\n".join(block.text for block in document_blocks(doc))
    for value in ["Amounts in millions, except per-share data", "(1,234.50)", "$0.0100", "−12.5%", "—"]:
        assert value in content


def test_multirow_table_headers_retain_period_and_unit_information():
    doc = DoclingDocument(name="report")
    values = [("Metric", "Year ended 2025", "Year ended 2024"), ("USD millions", "December 31", "December 31"), ("Income", "100", "90")]
    cells = [TableCell(text=value, start_row_offset_idx=row, end_row_offset_idx=row + 1, start_col_offset_idx=col, end_col_offset_idx=col + 1, column_header=row < 2) for row, items in enumerate(values) for col, value in enumerate(items)]
    doc.add_table(TableData(num_rows=3, num_cols=3, table_cells=cells))
    table = next(block for block in document_blocks(doc) if block.kind == "table")
    for value in ["Metric", "USD millions", "Year ended 2025", "Year ended 2024", "December 31"]:
        assert value in table.table_header
    assert "Income" in table.text and "100" in table.text and "90" in table.text
