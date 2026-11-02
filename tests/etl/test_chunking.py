"""Behavioral contracts for retrieval chunks, independent of the parser."""

import pytest

from etl.chunking import chunk_blocks
from etl.models import Block


def test_adjacent_paragraphs_merge_with_hierarchy_and_provenance():
    chunks = chunk_blocks("doc", [
        Block("Revenue grew.", headings=("Results", "Revenue"), pages=(1,), ref="#/texts/0"),
        Block("Margins improved.", headings=("Results", "Revenue"), pages=(2,), ref="#/texts/1"),
    ])
    assert len(chunks) == 1
    chunk = chunks[0]
    assert "Revenue grew." in chunk.text and "Margins improved." in chunk.text
    assert chunk.document_id == "doc"
    assert chunk.headings == ("Results", "Revenue")
    assert set(chunk.pages) == {1, 2}
    assert set(chunk.source_refs) == {"#/texts/0", "#/texts/1"}
    assert chunk.kind == "text"


def test_sections_do_not_merge_or_share_overlap():
    chunks = chunk_blocks("doc", [
        Block("FIRST SECTION " * 100, headings=("First",), pages=(1,), ref="a"),
        Block("SECOND SECTION", headings=("Second",), pages=(2,), ref="b"),
    ])
    second = [chunk for chunk in chunks if chunk.headings == ("Second",)]
    assert len(second) == 1
    assert second[0].text == "SECOND SECTION"
    assert second[0].pages == (2,)
    assert second[0].source_refs == ("b",)


def test_default_character_limit_and_overlap_for_long_block():
    text = "".join(chr(0x400 + index) for index in range(2300))
    chunks = chunk_blocks("doc", [Block(text, pages=(4,), ref="a")])
    assert len(chunks) >= 3
    assert all(0 < len(chunk.text) <= 1000 for chunk in chunks)
    assert chunks[0].text == text[:1000]
    assert chunks[1].text.startswith(chunks[0].text[-200:])
    assert all(chunk.pages == (4,) and chunk.source_refs == ("a",) for chunk in chunks)
    reconstructed = chunks[0].text + "".join(chunk.text[200:] for chunk in chunks[1:])
    assert reconstructed == text


def test_overlap_retains_provenance_from_previous_paragraph():
    chunks = chunk_blocks("doc", [
        Block("A" * 700, pages=(1,), ref="first"),
        Block("B" * 700, pages=(2,), ref="second"),
    ])
    assert len(chunks) >= 2
    assert all(len(chunk.text) <= 1000 for chunk in chunks)
    for chunk in chunks:
        if "A" in chunk.text:
            assert "first" in chunk.source_refs and 1 in chunk.pages
        if "B" in chunk.text:
            assert "second" in chunk.source_refs and 2 in chunk.pages


def test_empty_input_and_blank_blocks_are_ignored():
    assert chunk_blocks("doc", []) == []
    assert chunk_blocks("doc", [Block(""), Block(" \n\t")]) == []
    chunks = chunk_blocks("doc", [Block(" "), Block("Actual content", ref="real")])
    assert len(chunks) == 1
    assert chunks[0].text == "Actual content"
    assert chunks[0].source_refs == ("real",)


def test_ids_are_deterministic_unique_and_document_scoped():
    blocks = [Block("A" * 2200, headings=("Report",))]
    first = chunk_blocks("doc-a", blocks)
    assert first == chunk_blocks("doc-a", blocks)
    assert len({chunk.chunk_id for chunk in first}) == len(first)
    assert [chunk.ordinal for chunk in first] == list(range(len(first)))
    assert {chunk.chunk_id for chunk in first}.isdisjoint(
        chunk.chunk_id for chunk in chunk_blocks("doc-b", blocks)
    )


def test_zero_overlap_does_not_drop_or_duplicate_content():
    text = "abcdefghijklmnopqrstuvwxyz" * 10
    chunks = chunk_blocks("doc", [Block(text)], max_chars=60, overlap=0)
    assert "".join(chunk.text for chunk in chunks) == text
    assert all(len(chunk.text) <= 60 for chunk in chunks)


@pytest.mark.parametrize("max_chars,overlap", [(0, 0), (-1, 0), (100, -1), (100, 100), (100, 101)])
def test_invalid_chunking_parameters_fail(max_chars, overlap):
    with pytest.raises(ValueError):
        chunk_blocks("doc", [Block("content")], max_chars=max_chars, overlap=overlap)


def test_picture_annotations_remain_distinct_from_prose():
    chunks = chunk_blocks("doc", [
        Block("Revenue discussion", headings=("Results",), ref="text"),
        Block("Bar chart shows rising revenue", kind="picture", headings=("Results",), pages=(3,), ref="image"),
        Block("Further discussion", headings=("Results",), ref="after"),
    ])
    pictures = [chunk for chunk in chunks if chunk.kind == "picture"]
    assert len(pictures) == 1
    assert pictures[0].text == "Bar chart shows rising revenue"
    assert pictures[0].source_refs == ("image",)
    assert pictures[0].pages == (3,)
    assert all("Bar chart" not in chunk.text for chunk in chunks if chunk.kind == "text")


def test_table_chunks_repeat_headers_and_preserve_rows_that_fit():
    header = "| Metric | Value |\n| --- | --- |"
    rows = [f"| Metric {index} | {index * 1000} |" for index in range(15)]
    block = Block(header + "\n" + "\n".join(rows), kind="table", headings=("Financials",), pages=(7,), ref="table", table_header=header)
    chunks = chunk_blocks("doc", [block], max_chars=140, overlap=20)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.text.startswith(header)
        assert len(chunk.text) <= 140
        assert chunk.kind == "table"
        assert chunk.headings == ("Financials",)
        assert chunk.pages == (7,)
        assert chunk.source_refs == ("table",)
    assert all(any(row in chunk.text for chunk in chunks) for row in rows)


def test_oversized_table_row_still_respects_character_budget():
    header = "| Metric | Value |\n| --- | --- |"
    row = "| " + "Z" * 400 + " | 123 |"
    chunks = chunk_blocks("doc", [Block(header + "\n" + row, kind="table", table_header=header)], max_chars=100, overlap=10)
    assert len(chunks) > 1
    assert all(0 < len(chunk.text) <= 100 for chunk in chunks)
    assert all(chunk.text.startswith(header) for chunk in chunks)
    assert any("123" in chunk.text for chunk in chunks)
